"""Historical InteractionEvent → Learning Event v2 backfill.

Backfill is keyset-paginated by the legacy event's occurrence time and ID. It is
explicitly separate from the live dual-write flag: callers must opt into a write
job, and each page remains idempotent through the v2 event ID/checksum contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from event_schema import legacy_interaction_to_event
from services.learning_event_service import (
    LearningEventConflictError,
    append_learning_event,
)
from services.models import InteractionEvent


@dataclass(frozen=True, slots=True)
class LegacyEventCursor:
    occurred_at: datetime
    event_id: UUID


@dataclass(frozen=True, slots=True)
class BackfillPage:
    seen: int
    inserted: int
    duplicates: int
    next_cursor: LegacyEventCursor | None
    done: bool


class LearningEventBackfillConflictError(RuntimeError):
    """Raised when a legacy row conflicts with an existing v2 event ID."""


async def backfill_legacy_event_page(
    db: AsyncSession,
    *,
    student_id: UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    cursor: LegacyEventCursor | None = None,
    batch_size: int = 500,
    dry_run: bool = False,
) -> BackfillPage:
    """Backfill one deterministic page; caller commits the page when not dry-run."""

    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    for label, boundary in (("start", start), ("end", end)):
        if boundary is not None and (
            boundary.tzinfo is None or boundary.utcoffset() is None
        ):
            raise ValueError(f"backfill {label} must be timezone-aware")
    if cursor is not None and (
        cursor.occurred_at.tzinfo is None or cursor.occurred_at.utcoffset() is None
    ):
        raise ValueError("backfill cursor must be timezone-aware")

    stmt = select(InteractionEvent).order_by(
        InteractionEvent.occurred_at,
        InteractionEvent.id,
    )
    conditions: list[Any] = []
    if student_id is not None:
        conditions.append(InteractionEvent.student_id == student_id)
    if start is not None:
        conditions.append(InteractionEvent.occurred_at >= start)
    if end is not None:
        conditions.append(InteractionEvent.occurred_at < end)
    if cursor is not None:
        conditions.append(
            or_(
                InteractionEvent.occurred_at > cursor.occurred_at,
                and_(
                    InteractionEvent.occurred_at == cursor.occurred_at,
                    InteractionEvent.id > cursor.event_id,
                ),
            )
        )
    if conditions:
        stmt = stmt.where(*conditions)
    rows = list((await db.execute(stmt.limit(batch_size + 1))).scalars().all())
    has_more = len(rows) > batch_size
    rows = rows[:batch_size]
    if not rows:
        return BackfillPage(
            seen=0,
            inserted=0,
            duplicates=0,
            next_cursor=cursor,
            done=True,
        )

    inserted = 0
    duplicates = 0
    for legacy_row in rows:
        if dry_run:
            continue
        event = legacy_interaction_to_event(legacy_row)
        try:
            result = await append_learning_event(db, event)
        except LearningEventConflictError as exc:
            raise LearningEventBackfillConflictError(
                f"legacy event {legacy_row.id} conflicts with learning_events"
            ) from exc
        if result.inserted:
            inserted += 1
        else:
            duplicates += 1

    last = rows[-1]
    next_cursor = LegacyEventCursor(
        occurred_at=last.occurred_at,
        event_id=last.id,
    )
    return BackfillPage(
        seen=len(rows),
        inserted=inserted,
        duplicates=duplicates,
        next_cursor=next_cursor,
        done=not has_more,
    )
