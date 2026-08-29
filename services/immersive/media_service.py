"""Media upload, transcript attach, session continuity, telemetry."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.immersive.constants import (
    CONTENT_PROVENANCE,
    DEFAULT_MAX_MEDIA_BYTES,
    MEDIA_ALLOWED_EXTENSIONS,
    MEDIA_CONTENT_TYPES,
    MEDIA_TYPES,
    SOURCE_TYPES,
    SUBTITLE_ALLOWED_EXTENSIONS,
    TelemetryEventType,
)
from services.immersive.learning_units import ensure_units_for_segment
from services.immersive.transcript_parser import (
    TranscriptParseError,
    align_by_timing,
    parse_subtitle,
)
from services.models import (
    MediaAsset,
    MediaSession,
    MediaTelemetryEvent,
    Transcript,
    TranscriptSegment,
)
from services.storage import content_type_for_media, upload_media_file
from services.upload_safety import (
    UploadValidationError,
    validate_content_type,
    validate_filename,
    validate_size,
)


class MediaServiceError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def max_media_bytes() -> int:
    raw = os.environ.get("MAX_MEDIA_UPLOAD_BYTES", str(DEFAULT_MAX_MEDIA_BYTES))
    try:
        value = int(raw)
    except ValueError as exc:
        raise MediaServiceError("媒体上传大小配置无效") from exc
    if value <= 0:
        raise MediaServiceError("媒体上传大小配置无效")
    return value


def _detect_media_type(extension: str) -> str:
    if extension in {".mp4", ".webm"}:
        return "VIDEO"
    if extension in {".mp3", ".m4a", ".wav"}:
        return "AUDIO"
    raise MediaServiceError("不支持的媒体类型")


async def create_media_from_upload(
    db: AsyncSession,
    *,
    student_id: UUID,
    filename: str | None,
    content_type: str | None,
    data: bytes,
    title: str | None = None,
    language: str | None = None,
    content_provenance: str = "USER_UPLOADED",
) -> MediaAsset:
    if content_provenance not in CONTENT_PROVENANCE:
        raise MediaServiceError("invalid content_provenance")
    safe = validate_filename(filename, allowed_extensions=MEDIA_ALLOWED_EXTENSIONS)
    extension = Path(safe).suffix.lower()
    validate_size(len(data), limit=max_media_bytes())
    # Do not trust Content-Type alone — still validate when provided.
    expected = MEDIA_CONTENT_TYPES.get(extension)
    if expected and content_type and content_type.lower() not in expected:
        raise UploadValidationError("文件类型与内容不匹配")
    validate_content_type(safe, content_type)

    media_type = _detect_media_type(extension)
    media_id = uuid.uuid4()
    storage_ref = f"immersive/{student_id}/{media_id}{extension}"
    import asyncio

    await asyncio.to_thread(
        upload_media_file,
        storage_ref,
        data,
        content_type_for_media(extension),
    )
    asset = MediaAsset(
        id=media_id,
        owner_student_id=student_id,
        media_type=media_type,
        source_type="USER_UPLOAD",
        title=(title or Path(safe).stem)[:500],
        language=language,
        storage_ref=storage_ref,
        content_provenance=content_provenance,
        processing_state="READY",
        meta={"original_filename": safe, "byte_size": len(data)},
    )
    if asset.source_type not in SOURCE_TYPES or asset.media_type not in MEDIA_TYPES:
        raise MediaServiceError("invalid media fields")
    db.add(asset)
    await db.flush()
    return asset


async def get_owned_media(
    db: AsyncSession, *, student_id: UUID, media_id: UUID
) -> MediaAsset:
    asset = (
        await db.execute(
            select(MediaAsset).where(
                MediaAsset.id == media_id,
                MediaAsset.owner_student_id == student_id,
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        raise MediaServiceError("media not found", status_code=404)
    return asset


async def attach_transcript(
    db: AsyncSession,
    *,
    student_id: UUID,
    media_id: UUID,
    content: str,
    filename: str | None = None,
    language: str | None = None,
    role: str = "PRIMARY",
    extract_units: bool = True,
) -> dict[str, Any]:
    asset = await get_owned_media(db, student_id=student_id, media_id=media_id)
    if role not in {"PRIMARY", "TRANSLATION"}:
        raise MediaServiceError("invalid transcript role")
    hint = None
    if filename:
        safe = validate_filename(filename, allowed_extensions=SUBTITLE_ALLOWED_EXTENSIONS)
        hint = Path(safe).suffix.lower().lstrip(".")
    try:
        fmt, cues = parse_subtitle(content, format_hint=hint)
    except TranscriptParseError as exc:
        raise MediaServiceError(str(exc)) from exc

    transcript = Transcript(
        id=uuid.uuid4(),
        media_id=asset.id,
        role=role,
        source="uploaded_subtitle",
        format=fmt,
        language=language,
        provenance={"parser": "immersive.transcript_parser/1.0.0"},
    )
    db.add(transcript)
    await db.flush()

    translated_map: list[str | None] = [None] * len(cues)
    if role == "PRIMARY":
        # If a translation transcript already exists, attempt timing alignment.
        other = (
            await db.execute(
                select(Transcript).where(
                    Transcript.media_id == asset.id,
                    Transcript.role == "TRANSLATION",
                )
            )
        ).scalars().first()
        if other is not None:
            other_segs = (
                await db.execute(
                    select(TranscriptSegment)
                    .where(TranscriptSegment.transcript_id == other.id)
                    .order_by(TranscriptSegment.order_index)
                )
            ).scalars().all()
            from services.immersive.transcript_parser import ParsedCue

            translated_map = align_by_timing(
                cues,
                [
                    ParsedCue(s.order_index, s.start_ms, s.end_ms, s.text)
                    for s in other_segs
                ],
            )

    segment_rows: list[TranscriptSegment] = []
    for cue in cues:
        seg = TranscriptSegment(
            id=uuid.uuid4(),
            transcript_id=transcript.id,
            order_index=cue.order_index,
            start_ms=cue.start_ms,
            end_ms=cue.end_ms,
            text=cue.text,
            translated_text=translated_map[cue.order_index]
            if cue.order_index < len(translated_map)
            else None,
            language=language,
        )
        db.add(seg)
        segment_rows.append(seg)
    await db.flush()

    units_linked = 0
    if extract_units and role == "PRIMARY":
        for seg in segment_rows:
            created = await ensure_units_for_segment(
                db,
                media_id=asset.id,
                segment_id=seg.id,
                text=seg.text,
                language=language or "en",
            )
            units_linked += len(created)

    # If uploading TRANSLATION after PRIMARY, backfill translated_text by alignment.
    if role == "TRANSLATION":
        primary = (
            await db.execute(
                select(Transcript).where(
                    Transcript.media_id == asset.id,
                    Transcript.role == "PRIMARY",
                )
            )
        ).scalars().first()
        if primary is not None:
            primary_segs = (
                await db.execute(
                    select(TranscriptSegment)
                    .where(TranscriptSegment.transcript_id == primary.id)
                    .order_by(TranscriptSegment.order_index)
                )
            ).scalars().all()
            from services.immersive.transcript_parser import ParsedCue

            aligned = align_by_timing(
                [
                    ParsedCue(s.order_index, s.start_ms, s.end_ms, s.text)
                    for s in primary_segs
                ],
                cues,
            )
            for seg, translated in zip(primary_segs, aligned, strict=False):
                if translated is not None:
                    seg.translated_text = translated
            await db.flush()

    return {
        "transcript_id": str(transcript.id),
        "media_id": str(asset.id),
        "role": role,
        "format": fmt,
        "segment_count": len(segment_rows),
        "units_linked": units_linked,
    }


async def list_segments(
    db: AsyncSession,
    *,
    student_id: UUID,
    media_id: UUID,
    offset: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    await get_owned_media(db, student_id=student_id, media_id=media_id)
    primary = (
        await db.execute(
            select(Transcript).where(
                Transcript.media_id == media_id,
                Transcript.role == "PRIMARY",
            )
        )
    ).scalars().first()
    if primary is None:
        return {"items": [], "total": 0, "offset": offset, "limit": limit}
    total = len(
        (
            await db.execute(
                select(TranscriptSegment.id).where(
                    TranscriptSegment.transcript_id == primary.id
                )
            )
        ).all()
    )
    rows = (
        await db.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.transcript_id == primary.id)
            .order_by(TranscriptSegment.order_index)
            .offset(max(0, offset))
            .limit(min(max(limit, 1), 500))
        )
    ).scalars().all()
    return {
        "items": [
            {
                "segment_id": str(row.id),
                "order_index": row.order_index,
                "start_ms": row.start_ms,
                "end_ms": row.end_ms,
                "text": row.text,
                "translated_text": row.translated_text,
                "speaker": row.speaker,
                "language": row.language,
            }
            for row in rows
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
        "transcript_id": str(primary.id),
    }


async def start_or_resume_session(
    db: AsyncSession,
    *,
    student_id: UUID,
    media_id: UUID,
) -> MediaSession:
    await get_owned_media(db, student_id=student_id, media_id=media_id)
    existing = (
        await db.execute(
            select(MediaSession)
            .where(
                MediaSession.student_id == student_id,
                MediaSession.media_id == media_id,
                MediaSession.state == "ACTIVE",
            )
            .order_by(MediaSession.last_active_at.desc())
        )
    ).scalars().first()
    now = datetime.now(UTC)
    if existing is not None:
        existing.last_active_at = now
        await db.flush()
        return existing
    session = MediaSession(
        id=uuid.uuid4(),
        student_id=student_id,
        media_id=media_id,
        playhead_ms=0,
        scaffold_level=0,
        state="ACTIVE",
        started_at=now,
        last_active_at=now,
        meta={},
    )
    db.add(session)
    await db.flush()
    return session


async def update_session_continuity(
    db: AsyncSession,
    *,
    student_id: UUID,
    session_id: UUID,
    playhead_ms: int | None = None,
    current_segment_id: UUID | None = None,
    scaffold_level: int | None = None,
    state: str | None = None,
) -> MediaSession:
    session = (
        await db.execute(
            select(MediaSession).where(
                MediaSession.id == session_id,
                MediaSession.student_id == student_id,
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise MediaServiceError("session not found", status_code=404)
    if playhead_ms is not None:
        if playhead_ms < 0:
            raise MediaServiceError("playhead_ms must be >= 0")
        session.playhead_ms = playhead_ms
    if current_segment_id is not None:
        session.current_segment_id = current_segment_id
    if scaffold_level is not None:
        if scaffold_level not in {0, 1, 2, 3, 4, 5}:
            raise MediaServiceError("invalid scaffold_level")
        session.scaffold_level = scaffold_level
    if state is not None:
        session.state = state
        if state == "COMPLETED":
            session.completed_at = datetime.now(UTC)
    session.last_active_at = datetime.now(UTC)
    await db.flush()
    return session


async def append_telemetry(
    db: AsyncSession,
    *,
    student_id: UUID,
    event_type: str,
    media_id: UUID | None = None,
    session_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> UUID:
    allowed = {item.value for item in TelemetryEventType}
    if event_type not in allowed:
        raise MediaServiceError("invalid telemetry event_type")
    if media_id is not None:
        await get_owned_media(db, student_id=student_id, media_id=media_id)
    row = MediaTelemetryEvent(
        id=uuid.uuid4(),
        student_id=student_id,
        media_id=media_id,
        session_id=session_id,
        event_type=event_type,
        payload=payload or {},
        occurred_at=occurred_at or datetime.now(UTC),
        received_at=datetime.now(UTC),
    )
    db.add(row)
    await db.flush()
    return row.id
