from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from event_schema import legacy_interaction_to_event, replay_checksum
from services.learning_event_backfill_service import (
    LegacyEventCursor,
    LearningEventBackfillConflictError,
    backfill_legacy_event_page,
)


STUDENT_ID = UUID("11111111-1111-1111-1111-111111111111")
EVENT_ID = UUID("33333333-3333-3333-3333-333333333333")
OCCURRED_AT = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _Session:
    def __init__(self, *results):
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0)


def _legacy_row(*, event_id: UUID = EVENT_ID, occurred_at: datetime = OCCURRED_AT):
    return SimpleNamespace(
        id=event_id,
        student_id=STUDENT_ID,
        knowledge_point="linear-equations",
        question_id=None,
        source="review",
        is_correct=True,
        fsrs_rating=3,
        occurred_at=occurred_at,
    )


@pytest.mark.asyncio
async def test_backfill_page_dry_run_is_read_only_and_returns_cursor() -> None:
    db = _Session(_RowsResult([_legacy_row()]))

    page = await backfill_legacy_event_page(
        db,
        student_id=STUDENT_ID,
        batch_size=10,
        dry_run=True,
    )

    assert page.seen == 1
    assert page.inserted == 0
    assert page.duplicates == 0
    assert page.done is True
    assert page.next_cursor == LegacyEventCursor(OCCURRED_AT, EVENT_ID)
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_backfill_page_is_idempotent_and_preserves_legacy_id() -> None:
    row = _legacy_row()
    event = legacy_interaction_to_event(row)
    db = _Session(_RowsResult([row]), _ScalarResult(None), _ScalarResult(replay_checksum((event,))))

    page = await backfill_legacy_event_page(db, batch_size=10)

    assert page.seen == 1
    assert page.inserted == 0
    assert page.duplicates == 1
    assert page.next_cursor is not None
    assert page.next_cursor.event_id == EVENT_ID
    assert len(db.statements) == 3


@pytest.mark.asyncio
async def test_backfill_conflicting_event_id_fails_closed() -> None:
    row = _legacy_row()
    db = _Session(_RowsResult([row]), _ScalarResult(None), _ScalarResult("different" * 8))

    with pytest.raises(LearningEventBackfillConflictError, match=str(EVENT_ID)):
        await backfill_legacy_event_page(db, batch_size=10)


@pytest.mark.asyncio
async def test_backfill_cursor_excludes_previously_processed_rows() -> None:
    later_id = UUID("44444444-4444-4444-4444-444444444444")
    db = _Session(_RowsResult([_legacy_row(event_id=later_id, occurred_at=OCCURRED_AT)]))

    await backfill_legacy_event_page(
        db,
        cursor=LegacyEventCursor(OCCURRED_AT, EVENT_ID),
        batch_size=10,
        dry_run=True,
    )

    sql = str(db.statements[0])
    assert "interaction_events" in sql
    assert "occurred_at" in sql
