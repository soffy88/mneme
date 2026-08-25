"""Keyset backfill for legacy InteractionEvent rows.

Usage:
    .venv/bin/python scripts/backfill_learning_events.py --dry-run
    LEARNING_EVENT_V2_BACKFILL_ENABLED=1 \
        .venv/bin/python scripts/backfill_learning_events.py

Writes are fail-closed behind ``LEARNING_EVENT_V2_BACKFILL_ENABLED``.  The
script commits one page at a time and can be restarted safely because the v2
event ID is the legacy row ID and ingestion is checksum/idempotency guarded.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

# Keep direct script execution identical to the Docker/pytest import closure.
_ROOT = Path(__file__).resolve().parents[1]
for _path in (
    _ROOT / "vendor",
    _ROOT / "packages/mneme-core",
    _ROOT / "packages/mneme-agent",
    _ROOT / "packages/event-schema",
    _ROOT,
):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from obase.db import SessionLocal
from services.feature_flags import learning_event_v2_backfill_enabled
from services.learning_event_backfill_service import (
    LegacyEventCursor,
    backfill_legacy_event_page,
)


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--student-id", type=UUID)
    parser.add_argument("--start", type=_datetime)
    parser.add_argument("--end", type=_datetime)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="scan and count rows without inserting or committing",
    )
    return parser


async def _run(args: argparse.Namespace) -> dict[str, int | bool]:
    if not args.dry_run and not learning_event_v2_backfill_enabled():
        raise RuntimeError(
            "refusing to write: set LEARNING_EVENT_V2_BACKFILL_ENABLED=1 "
            "for an approved backfill window"
        )

    totals = {"seen": 0, "inserted": 0, "duplicates": 0}
    cursor: LegacyEventCursor | None = None
    async with SessionLocal() as db:
        while True:
            page = await backfill_legacy_event_page(
                db,
                student_id=args.student_id,
                start=args.start,
                end=args.end,
                cursor=cursor,
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            totals["seen"] += page.seen
            totals["inserted"] += page.inserted
            totals["duplicates"] += page.duplicates
            if not args.dry_run:
                await db.commit()
            if page.done:
                break
            cursor = page.next_cursor
    return {**totals, "dry_run": args.dry_run}


def main() -> None:
    args = _parser().parse_args()
    print(json.dumps(asyncio.run(_run(args)), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
