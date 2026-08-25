from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from event_schema import LearningEvent, legacy_interaction_to_event, replay_checksum
from obase.cognitive_store import PgStore
from services.feature_flags import (
    LEARNING_EVENT_V2_DUAL_WRITE,
    learning_event_v2_dual_write_enabled,
)
from services.learning_event_service import (
    LearningEventConflictError,
    _event_insert_statement,
    _event_record_values,
    append_learning_event,
    append_legacy_interaction_as_v2,
    learning_event_record_to_event,
)


EVENT_ID = UUID("33333333-3333-3333-3333-333333333333")
STUDENT_ID = UUID("11111111-1111-1111-1111-111111111111")
OCCURRED_AT = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def _event(*, response: dict | None = None) -> LearningEvent:
    return LearningEvent(
        event_id=EVENT_ID,
        actor_id=STUDENT_ID,
        student_id=STUDENT_ID,
        occurred_at=OCCURRED_AT,
        received_at=OCCURRED_AT,
        source="web",
        action="attempted",
        object_type="question",
        object_id="question-1",
        knowledge_refs=["kc-1"],
        response=response,
    )


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, *results):
        self.results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.results.pop(0))


def test_event_record_mapping_has_no_projection_fields_and_stable_checksum() -> None:
    event = _event(response={"answer": "x"})
    values = _event_record_values(event)

    assert values["event_id"] == EVENT_ID
    assert values["student_id"] == STUDENT_ID
    assert values["response"] == {"answer": "x"}
    assert values["event_checksum"] == replay_checksum((event,))
    assert "p_mastery" not in values
    assert "is_mastered" not in values


def test_insert_statement_is_idempotent_and_append_only() -> None:
    sql = str(_event_insert_statement(_event()).compile(dialect=postgresql.dialect()))

    assert "INSERT INTO learning_events" in sql
    assert "ON CONFLICT (event_id) DO NOTHING" in sql
    assert "UPDATE" not in sql


@pytest.mark.asyncio
async def test_append_learning_event_reports_first_insert() -> None:
    event = _event()
    db = _Session(EVENT_ID)

    result = await append_learning_event(db, event)

    assert result.inserted is True
    assert result.duplicate is False
    assert result.event_id == EVENT_ID
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_append_learning_event_accepts_exact_retry_as_duplicate() -> None:
    event = _event()
    db = _Session(None, replay_checksum((event,)))

    result = await append_learning_event(db, event)

    assert result.inserted is False
    assert result.duplicate is True
    assert len(db.statements) == 2


@pytest.mark.asyncio
async def test_append_learning_event_rejects_same_id_with_different_payload() -> None:
    event = _event()
    db = _Session(None, "different" * 8)

    with pytest.raises(LearningEventConflictError, match="different payload"):
        await append_learning_event(db, event)


@pytest.mark.asyncio
async def test_legacy_dual_write_uses_the_legacy_event_id() -> None:
    db = _Session(EVENT_ID)

    result = await append_legacy_interaction_as_v2(
        db,
        event_id=EVENT_ID,
        student_id=STUDENT_ID,
        knowledge_point="kc-1",
        event_data={
            "source": "paper",
            "is_correct": True,
            "occurred_at": OCCURRED_AT,
        },
    )

    assert result.inserted is True
    assert result.event_id == EVENT_ID
    assert len(db.statements) == 1


@pytest.mark.asyncio
async def test_pg_store_dual_writer_uses_one_id_for_both_fact_rows() -> None:
    db = _Session(EVENT_ID, EVENT_ID)

    async def writer(event_id, student_id, knowledge_point, event_data):
        return await append_legacy_interaction_as_v2(
            db,
            event_id=event_id,
            student_id=student_id,
            knowledge_point=knowledge_point,
            event_data=event_data,
        )

    store = PgStore(db, learning_event_writer=writer)
    inserted_id = await store.append_event(
        STUDENT_ID,
        "kc-1",
        {
            "source": "review",
            "is_correct": True,
            "occurred_at": OCCURRED_AT,
        },
    )

    assert inserted_id == EVENT_ID
    assert len(db.statements) == 2
    assert "INSERT INTO interaction_events" in str(db.statements[0])
    assert "INSERT INTO learning_events" in str(db.statements[1])


def test_database_record_round_trip_preserves_replay_checksum() -> None:
    event = legacy_interaction_to_event(
        {
            "id": EVENT_ID,
            "student_id": STUDENT_ID,
            "knowledge_point": "kc-1",
            "occurred_at": OCCURRED_AT,
            "source": "review",
            "is_correct": True,
            "fsrs_rating": 3,
            "predicted_r": 0.82,
            "self_explanation": "我先找到了共同分母。",
        }
    )
    hydrated = learning_event_record_to_event(_event_record_values(event))

    assert hydrated == event
    assert replay_checksum((hydrated,)) == replay_checksum((event,))
    assert hydrated.response == {"self_explanation": "我先找到了共同分母。"}
    assert hydrated.provenance.metadata["predicted_r"] == 0.82


def test_v2_dual_write_is_off_by_default_and_explicitly_enableable(monkeypatch) -> None:
    monkeypatch.delenv(LEARNING_EVENT_V2_DUAL_WRITE, raising=False)
    assert learning_event_v2_dual_write_enabled() is False

    monkeypatch.setenv(LEARNING_EVENT_V2_DUAL_WRITE, "true")
    assert learning_event_v2_dual_write_enabled() is True
