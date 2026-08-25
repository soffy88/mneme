from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from event_schema import LearningEvent
from services.learning_event_replay_service import ReplayConfig, replay_events


STUDENT_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_STUDENT_ID = UUID("22222222-2222-2222-2222-222222222222")
BASE_TIME = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def _event(
    event_id: str,
    *,
    occurred_at: datetime = BASE_TIME,
    received_at: datetime | None = None,
    student_id: UUID = STUDENT_ID,
    source: str = "review",
    action: str = "attempted",
    correctness: bool | None = True,
    fsrs_rating: int | None = 3,
    knowledge_refs: list[str] | None = None,
    supersedes_event_id: UUID | None = None,
    correction_reason: str | None = None,
) -> LearningEvent:
    return LearningEvent(
        event_id=UUID(event_id),
        actor_id=student_id,
        student_id=student_id,
        occurred_at=occurred_at,
        received_at=received_at or occurred_at,
        source=source,
        action=action,
        object_type="question",
        object_id="question-1",
        knowledge_refs=knowledge_refs or ["kc-1"],
        outcome={"correctness": correctness, "fsrs_rating": fsrs_rating},
        supersedes_event_id=supersedes_event_id,
        correction_reason=correction_reason,
    )


@pytest.mark.asyncio
async def test_replay_is_deterministic_and_excludes_non_attempt_facts() -> None:
    events = [
        _event("00000000-0000-0000-0000-000000000003", fsrs_rating=1),
        _event(
            "00000000-0000-0000-0000-000000000002",
            occurred_at=BASE_TIME + timedelta(hours=1),
            fsrs_rating=4,
        ),
        _event(
            "00000000-0000-0000-0000-000000000004",
            occurred_at=BASE_TIME + timedelta(hours=2),
            source="fire_credit",
            action="credited",
        ),
        _event(
            "00000000-0000-0000-0000-000000000005",
            occurred_at=BASE_TIME + timedelta(hours=3),
            knowledge_refs=["kc-1", "kc-2"],
        ),
        _event(
            "00000000-0000-0000-0000-000000000006",
            occurred_at=BASE_TIME + timedelta(hours=4),
            student_id=OTHER_STUDENT_ID,
        ),
        _event(
            "00000000-0000-0000-0000-000000000007",
            occurred_at=BASE_TIME + timedelta(hours=5),
            action="corrected",
            supersedes_event_id=UUID("00000000-0000-0000-0000-000000000003"),
            correction_reason="late verifier result",
        ),
    ]
    config = ReplayConfig(priors={"kc-1": {"p_init": 0.3, "p_transit": 0.2, "p_guess": 0.1, "p_slip": 0.1}})
    computed_at = BASE_TIME + timedelta(days=1)

    first = await replay_events(
        events,
        student_id=STUDENT_ID,
        config=config,
        computed_at=computed_at,
    )
    second = await replay_events(
        list(reversed(events)),
        student_id=STUDENT_ID,
        config=config,
        computed_at=computed_at,
    )

    assert first.input_checksum == second.input_checksum
    assert first.projection_checksum == second.projection_checksum
    assert first.states == second.states
    assert first.event_count == 6
    assert first.applied_event_count == 1
    assert first.evidence_refs == ("00000000-0000-0000-0000-000000000002",)
    assert {item["reason"] for item in first.skipped_events} == {
        "derived_credit",
        "unsupported_event_shape",
        "student_mismatch",
        "correction",
        "superseded_by_correction",
    }
    json.dumps(first.as_dict())


@pytest.mark.asyncio
async def test_replay_as_of_excludes_future_occurrence_and_receipt() -> None:
    cutoff = BASE_TIME + timedelta(hours=1)
    events = [
        _event("00000000-0000-0000-0000-000000000011"),
        _event(
            "00000000-0000-0000-0000-000000000012",
            occurred_at=BASE_TIME + timedelta(minutes=30),
            received_at=cutoff + timedelta(seconds=1),
        ),
        _event(
            "00000000-0000-0000-0000-000000000013",
            occurred_at=cutoff,
        ),
    ]

    projection = await replay_events(
        events,
        student_id=STUDENT_ID,
        as_of=cutoff,
        computed_at=cutoff,
    )

    assert projection.event_count == 2
    assert projection.applied_event_count == 2
