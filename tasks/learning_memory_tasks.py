"""Manual Learning Event v2 backfill and read-only replay jobs.

Neither task is scheduled by default. Backfill is fail-closed behind an explicit
environment flag; replay never commits and only returns a deterministic projection
checksum plus operational metadata.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.feature_flags import learning_event_v2_backfill_enabled
from services.learning_event_backfill_service import backfill_legacy_event_page
from services.learning_event_replay_service import replay_student_from_db

from tasks.celery_app import celery_app


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("task datetime arguments must be timezone-aware")
    return parsed


async def _run_backfill(
    *,
    student_id: str | None,
    start: str | None,
    end: str | None,
    batch_size: int,
    max_pages: int,
    dry_run: bool,
) -> dict:
    if not dry_run and not learning_event_v2_backfill_enabled():
        return {
            "status": "disabled",
            "reason": "set LEARNING_EVENT_V2_BACKFILL_ENABLED=1 for writes",
        }
    if max_pages < 1:
        raise ValueError("max_pages must be >= 1")

    sid = UUID(student_id) if student_id else None
    start_at = _parse_datetime(start)
    end_at = _parse_datetime(end)
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    totals = {
        "seen": 0,
        "inserted": 0,
        "duplicates": 0,
        "pages": 0,
    }
    cursor = None
    completed = False
    try:
        async with factory() as db:
            for _ in range(max_pages):
                page = await backfill_legacy_event_page(
                    db,
                    student_id=sid,
                    start=start_at,
                    end=end_at,
                    cursor=cursor,
                    batch_size=batch_size,
                    dry_run=dry_run,
                )
                totals["seen"] += page.seen
                totals["inserted"] += page.inserted
                totals["duplicates"] += page.duplicates
                totals["pages"] += 1
                if not dry_run:
                    await db.commit()
                cursor = page.next_cursor
                if page.done:
                    completed = True
                    break
        return {
            **totals,
            "status": (
                "dry_run"
                if dry_run
                else ("completed" if completed else "page_limit_reached")
            ),
            "done": completed,
        }
    finally:
        await engine.dispose()


async def _run_replay(
    *,
    student_id: str,
    start: str | None,
    end: str | None,
    as_of: str | None,
) -> dict:
    sid = UUID(student_id)
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with factory() as db:
            projection = await replay_student_from_db(
                db,
                sid,
                start=_parse_datetime(start),
                end=_parse_datetime(end),
                as_of=_parse_datetime(as_of),
            )
            return projection.as_dict()
    finally:
        await engine.dispose()


@celery_app.task(name="tasks.backfill_learning_events")
def backfill_learning_events_task(
    student_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    batch_size: int = 500,
    max_pages: int = 1000,
    dry_run: bool = True,
) -> dict:
    """Manual legacy→v2 backfill; writes require the explicit backfill flag."""

    return asyncio.run(
        _run_backfill(
            student_id=student_id,
            start=start,
            end=end,
            batch_size=batch_size,
            max_pages=max_pages,
            dry_run=dry_run,
        )
    )


@celery_app.task(name="tasks.replay_learning_events")
def replay_learning_events_task(
    student_id: str,
    start: str | None = None,
    end: str | None = None,
    as_of: str | None = None,
) -> dict:
    """Manual read-only v2 replay; no production projection is written."""

    return asyncio.run(
        _run_replay(
            student_id=student_id,
            start=start,
            end=end,
            as_of=as_of,
        )
    )
