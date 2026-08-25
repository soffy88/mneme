from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from event_schema import (
    EventOutcome,
    LearningEvent,
    PrivacyClass,
    canonical_replay_events,
    legacy_interaction_to_event,
    replay_checksum,
)


UTC = timezone.utc
STUDENT_ID = UUID("11111111-1111-1111-1111-111111111111")
QUESTION_ID = UUID("22222222-2222-2222-2222-222222222222")
BASE_TIME = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def make_event(
    *,
    event_id: UUID | None = None,
    occurred_at: datetime = BASE_TIME,
    received_at: datetime | None = None,
    **overrides: object,
) -> LearningEvent:
    values: dict[str, object] = {
        "event_id": event_id or uuid4(),
        "actor_id": STUDENT_ID,
        "student_id": STUDENT_ID,
        "occurred_at": occurred_at,
        "received_at": received_at or occurred_at,
        "source": "web",
        "action": "attempted",
        "object_type": "question",
        "object_id": str(QUESTION_ID),
        "knowledge_refs": ["kp-1"],
    }
    values.update(overrides)
    return LearningEvent.model_validate(values)


def test_learning_event_v2_rejects_unversioned_or_unknown_mastery_fields() -> None:
    with pytest.raises(ValidationError):
        make_event(schema_version="1")

    with pytest.raises(ValidationError):
        make_event(p_mastery=0.9)


def test_learning_event_requires_timezone_aware_timestamps() -> None:
    with pytest.raises(ValidationError):
        make_event(occurred_at=datetime(2026, 8, 24, 12, 0))


def test_correction_requires_superseded_event_and_reason() -> None:
    with pytest.raises(ValidationError):
        make_event(action="corrected", correction_reason="typo")

    superseded_id = uuid4()
    with pytest.raises(ValidationError):
        make_event(supersedes_event_id=superseded_id)
    with pytest.raises(ValidationError):
        make_event(
            supersedes_event_id=superseded_id,
            correction_reason="reason without corrected action",
        )

    corrected = make_event(
        action="corrected",
        supersedes_event_id=superseded_id,
        correction_reason="late grading correction",
    )
    assert corrected.supersedes_event_id == superseded_id
    assert corrected.correction_reason == "late grading correction"


def test_legacy_interaction_adapter_preserves_learning_facts() -> None:
    occurred_at = BASE_TIME - timedelta(minutes=5)
    legacy = SimpleNamespace(
        id=uuid4(),
        student_id=STUDENT_ID,
        question_id=QUESTION_ID,
        knowledge_point="linear-equations",
        occurred_at=occurred_at,
        source="fire_credit",
        item_difficulty=0.72,
        is_correct=True,
        fsrs_rating=4,
        time_spent_seconds=8,
        days_since_last=2.0,
        is_interleaved=True,
        predicted_confidence=0.6,
        fire_meta={"rule": "credit"},
    )

    event = legacy_interaction_to_event(legacy)

    assert event.schema_version == "2"
    assert event.event_id == legacy.id
    assert event.student_id == STUDENT_ID
    assert event.object_id == str(QUESTION_ID)
    assert event.knowledge_refs == ["linear-equations"]
    assert event.action == "credited"
    assert event.source == "fire_credit"
    assert event.item_features.difficulty == 0.72
    assert event.outcome == EventOutcome(correctness=True, fsrs_rating=4)
    assert event.process_signals.time_spent_seconds == 8
    assert event.process_signals.days_since_last == 2.0
    assert event.process_signals.interleaved is True
    assert event.metacognitive.jol_confidence == 0.6
    assert event.intervention == {"kind": "fire_credit", "metadata": {"rule": "credit"}}
    assert event.received_at == occurred_at
    assert event.provenance.adapter == "interaction_event_v1"
    assert event.privacy_class == PrivacyClass.P1
    assert event.is_derived_credit is True


def test_legacy_interaction_adapter_accepts_mapping_and_keeps_normal_attempt() -> None:
    event = legacy_interaction_to_event(
        {
            "id": str(uuid4()),
            "student_id": str(STUDENT_ID),
            "question_id": str(QUESTION_ID),
            "knowledge_point": "fractions",
            "occurred_at": BASE_TIME.isoformat(),
            "is_correct": False,
            "fsrs_rating": 1,
        }
    )

    assert event.action == "attempted"
    assert event.source == "legacy"
    assert event.outcome == EventOutcome(correctness=False, fsrs_rating=1)
    assert event.provenance.metadata["legacy_id"] == str(event.event_id)


def test_legacy_adapter_does_not_turn_missing_correctness_into_false() -> None:
    event = legacy_interaction_to_event(
        {
            "id": str(uuid4()),
            "knowledge_point": "fractions",
            "occurred_at": BASE_TIME,
        }
    )

    assert event.outcome is not None
    assert event.outcome.correctness is None


def test_replay_boundaries_require_timezone_aware_values() -> None:
    event = make_event()
    with pytest.raises(ValueError, match="timezone-aware"):
        canonical_replay_events([event], as_of=datetime(2026, 8, 24, 12, 0))


def test_canonical_replay_order_is_total_and_as_of_is_conservative() -> None:
    tie_time = BASE_TIME
    first_id = UUID("00000000-0000-0000-0000-000000000001")
    second_id = UUID("00000000-0000-0000-0000-000000000002")
    first = make_event(event_id=first_id, occurred_at=tie_time)
    second = make_event(
        event_id=second_id,
        occurred_at=tie_time,
        received_at=tie_time + timedelta(seconds=1),
    )
    future_received = make_event(
        event_id=uuid4(),
        occurred_at=tie_time - timedelta(seconds=1),
        received_at=tie_time + timedelta(seconds=10),
    )

    ordered = canonical_replay_events([future_received, second, first])
    assert [event.event_id for event in ordered] == [
        future_received.event_id,
        first_id,
        second_id,
    ]
    assert canonical_replay_events(ordered, as_of=tie_time) == (first,)
    assert canonical_replay_events(ordered, end=tie_time) == (future_received,)


def test_replay_checksum_is_order_independent_but_content_sensitive() -> None:
    first = make_event(event_id=UUID("00000000-0000-0000-0000-000000000001"))
    second = make_event(
        event_id=UUID("00000000-0000-0000-0000-000000000002"),
        occurred_at=BASE_TIME + timedelta(seconds=1),
    )

    checksum = replay_checksum([first, second])
    assert checksum == replay_checksum([second, first])
    assert len(checksum) == 64
    assert checksum != replay_checksum(
        [second, first.model_copy(update={"response": {"variant": "different"}})]
    )
