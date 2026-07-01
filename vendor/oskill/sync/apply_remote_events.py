"""oskill.sync.apply_remote_events — pull remote changefeed events and apply to local DB."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from oprim._logging import log
from oprim.changefeed.schema import ChangefeedEvent, EventType
from oprim.meta_db.duckdb import MetaDB

from oskill.sync.errors import ApplyError

_DEFAULT_STATE_DIR = Path.home() / ".stratum"


@dataclass
class SyncApplyResult:
    applied_count: int
    skipped_count: int
    conflict_count: int
    last_applied_seq: int
    errors: list[str] = field(default_factory=list)


def _state_path(user_id: str, device_id: str, state_dir: Path) -> Path:
    return state_dir / f"sync_state_{user_id}_{device_id}.json"


def _load_state(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ── event appliers ────────────────────────────────────────────────────────────


def _apply_substrate_upsert(db: MetaDB, event: ChangefeedEvent) -> None:
    p = event.payload
    db.execute("DELETE FROM substrates WHERE id = ?", [p.get("id")])
    db.execute(
        "INSERT INTO substrates "
        "(id, user_id, title, mime, source_path, file_hash, byte_size, page_count, "
        "parser, language, has_cjk, is_scanned, is_pinned, pinned_at, pin_priority, "
        "created_at, updated_at, meta_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            p.get("id"),
            event.user_id,
            p.get("title"),
            p.get("mime"),
            p.get("source_path"),
            p.get("file_hash"),
            p.get("byte_size"),
            p.get("page_count"),
            p.get("parser"),
            p.get("language"),
            p.get("has_cjk"),
            p.get("is_scanned"),
            p.get("is_pinned", False),
            p.get("pinned_at"),
            p.get("pin_priority", 0),
            p.get("created_at"),
            p.get("updated_at"),
            p.get("meta_json", "{}"),
        ],
    )


def _apply_substrate_delete(db: MetaDB, event: ChangefeedEvent) -> None:
    row_id = event.aggregate_id or event.payload.get("id")
    db.execute("DELETE FROM substrates WHERE id = ?", [row_id])


def _apply_substrate_pin(db: MetaDB, event: ChangefeedEvent) -> None:
    meta = event.payload.get("meta_json")
    if meta is not None:
        db.execute(
            "UPDATE substrates SET meta_json = ? WHERE id = ?",
            [meta, event.aggregate_id],
        )


def _apply_substrate_unpin(db: MetaDB, event: ChangefeedEvent) -> None:
    meta = event.payload.get("meta_json")
    if meta is not None:
        db.execute(
            "UPDATE substrates SET meta_json = ? WHERE id = ?",
            [meta, event.aggregate_id],
        )


def _apply_note_upsert(db: MetaDB, event: ChangefeedEvent) -> None:
    p = event.payload
    db.execute("DELETE FROM notes WHERE id = ?", [p.get("id")])
    db.execute(
        "INSERT INTO notes "
        "(id, title, content, wikilinks, substrate_id, meta_json, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            p.get("id"),
            p.get("title"),
            p.get("content"),
            p.get("wikilinks", "[]"),
            p.get("substrate_id"),
            p.get("meta_json", "{}"),
            p.get("created_at"),
            p.get("updated_at"),
        ],
    )


def _apply_note_delete(db: MetaDB, event: ChangefeedEvent) -> None:
    row_id = event.aggregate_id or event.payload.get("id")
    db.execute("DELETE FROM notes WHERE id = ?", [row_id])


def _apply_concept_upsert(db: MetaDB, event: ChangefeedEvent) -> None:
    p = event.payload
    db.execute("DELETE FROM concepts WHERE id = ?", [p.get("id")])
    db.execute(
        "INSERT INTO concepts "
        "(id, user_id, name, type, aliases, wikilink, substrate_refs, related_concept_ids, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            p.get("id"),
            event.user_id,
            p.get("name"),
            p.get("type", "concept_idea"),
            p.get("aliases"),
            p.get("wikilink"),
            p.get("substrate_refs"),
            p.get("related_concept_ids"),
            p.get("created_at"),
        ],
    )


def _apply_concept_delete(db: MetaDB, event: ChangefeedEvent) -> None:
    row_id = event.aggregate_id or event.payload.get("id")
    db.execute("DELETE FROM concepts WHERE id = ?", [row_id])


def _apply_concept_link(db: MetaDB, event: ChangefeedEvent) -> None:
    substrate_refs = event.payload.get("substrate_refs")
    if substrate_refs is not None:
        db.execute(
            "UPDATE concepts SET substrate_refs = ? WHERE id = ?",
            [substrate_refs, event.aggregate_id],
        )


def _apply_concept_unlink(db: MetaDB, event: ChangefeedEvent) -> None:
    substrate_refs = event.payload.get("substrate_refs")
    if substrate_refs is not None:
        db.execute(
            "UPDATE concepts SET substrate_refs = ? WHERE id = ?",
            [substrate_refs, event.aggregate_id],
        )


_HANDLERS: dict[str, object] = {
    EventType.SUBSTRATE_CREATED.value: _apply_substrate_upsert,
    EventType.SUBSTRATE_UPDATED.value: _apply_substrate_upsert,
    EventType.SUBSTRATE_DELETED.value: _apply_substrate_delete,
    EventType.SUBSTRATE_PINNED.value: _apply_substrate_pin,
    EventType.SUBSTRATE_UNPINNED.value: _apply_substrate_unpin,
    EventType.DERIVATIVE_CREATED.value: _apply_concept_upsert,
    EventType.DERIVATIVE_DELETED.value: _apply_concept_delete,
    EventType.NOTE_CREATED.value: _apply_note_upsert,
    EventType.NOTE_UPDATED.value: _apply_note_upsert,
    EventType.NOTE_DELETED.value: _apply_note_delete,
    EventType.CONCEPT_CREATED.value: _apply_concept_upsert,
    EventType.CONCEPT_LINKED.value: _apply_concept_link,
    EventType.CONCEPT_UNLINKED.value: _apply_concept_unlink,
}


def _apply_one(db: MetaDB, event: ChangefeedEvent) -> bool:
    handler = _HANDLERS.get(event.event_type.value)
    if handler is None:
        log.warning("apply_remote_unknown_event_type", event_type=event.event_type.value)
        return False
    handler(db, event)  # type: ignore[call-arg]
    return True


def _parse_jsonl(content: str) -> list[dict]:
    events = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            log.warning("apply_remote_malformed_jsonl_line", error=str(exc))
    return events


async def apply_remote_events(
    user_id: str,
    device_id: str,
    db: MetaDB,
    storage_adapter,
    *,
    since_seq: int = 0,
    state_dir: Path | None = None,
) -> SyncApplyResult:
    """Download remote changefeed JSONL files and apply events to local DB.

    Lists all files under /Stratum/changefeed/ in storage, skips files from the
    current device_id (those are our own events already in the local DB), and
    applies events that haven't been processed yet.

    State tracking uses a set of processed file paths stored in the sync_state
    JSON file so files are never re-applied on subsequent calls.
    """
    state_dir = state_dir or _DEFAULT_STATE_DIR
    state_file = _state_path(user_id, device_id, state_dir)
    state = _load_state(state_file)
    processed_files: list[str] = state.get("processed_remote_files", [])
    processed_set: set[str] = set(processed_files)

    applied_count = 0
    skipped_count = 0
    conflict_count = 0
    last_applied_seq = int(state.get("last_applied_seq", since_seq))
    errors: list[str] = []
    newly_processed: list[str] = []

    # Collect candidate files — skip own device's files and already-processed ones.
    # candidate_files: list of (name, file_id) tuples.
    # name: the logical key used for deduplication (storage_file.name — the filename).
    # file_id: the handle passed to download() (provider-specific: abs path for local,
    #          GDrive ID for gdrive).
    # Filename convention: events_{device_id}_{seq_start}_{seq_end}.jsonl
    candidate_files: list[tuple[str, str]] = []
    try:
        async for storage_file in storage_adapter.list_files("/Stratum/changefeed", recursive=True):
            fname = storage_file.name
            fid = storage_file.file_id
            # Skip files originating from this device
            if fname.startswith(f"events_{device_id}_"):
                continue
            if fname in processed_set:
                continue
            candidate_files.append((fname, fid))
    except Exception as exc:
        log.error("apply_remote_list_failed", error=str(exc))
        raise ApplyError(f"Failed to list remote changefeed files: {exc}") from exc

    if not candidate_files:
        log.info("apply_remote_nothing_new", user_id=user_id, device_id=device_id)
        return SyncApplyResult(
            applied_count=0,
            skipped_count=0,
            conflict_count=0,
            last_applied_seq=last_applied_seq,
        )

    for fname, fid in sorted(candidate_files):
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".jsonl", delete=False) as tf:
            tmp_path = tf.name

        try:
            await storage_adapter.download(fid, tmp_path)
            content = Path(tmp_path).read_text(encoding="utf-8")
        except Exception as exc:
            log.error("apply_remote_download_failed", file=fname, error=str(exc))
            errors.append(f"download:{fname}:{exc}")
            continue
        finally:
            os.unlink(tmp_path)

        raw_events = _parse_jsonl(content)
        for raw in raw_events:
            try:
                event = ChangefeedEvent.from_dict(raw)
            except Exception as exc:
                log.warning("apply_remote_parse_failed", error=str(exc))
                skipped_count += 1
                continue

            # Skip events already applied (by seq — cross-device seq not comparable,
            # but within a single device file they are monotonically increasing)
            if event.seq <= since_seq and since_seq > 0:
                skipped_count += 1
                continue

            try:
                if _apply_one(db, event):
                    applied_count += 1
                    last_applied_seq = max(last_applied_seq, event.seq)
                else:
                    skipped_count += 1
            except Exception as exc:
                log.error(
                    "apply_remote_event_failed",
                    event_type=event.event_type.value,
                    seq=event.seq,
                    error=str(exc),
                )
                errors.append(f"apply:{event.event_type.value}:{exc}")
                conflict_count += 1

        newly_processed.append(fname)

    # Persist updated state
    state["last_applied_seq"] = last_applied_seq
    state["processed_remote_files"] = sorted(processed_set | set(newly_processed))
    _save_state(state_file, state)

    log.info(
        "apply_remote_done",
        applied=applied_count,
        skipped=skipped_count,
        conflicts=conflict_count,
        user_id=user_id,
    )
    return SyncApplyResult(
        applied_count=applied_count,
        skipped_count=skipped_count,
        conflict_count=conflict_count,
        last_applied_seq=last_applied_seq,
        errors=errors,
    )
