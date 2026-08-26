from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from event_schema import EvaluationPhase, EventOutcome, LearningEvent
from services.cognitive_state_v2 import CognitiveStateV2


def test_independent_no_ai_requires_explicit_contamination_flags():
    base = {
        "student_id": UUID("11111111-1111-1111-1111-111111111111"),
        "occurred_at": datetime(2026, 8, 1, tzinfo=UTC),
        "received_at": datetime(2026, 8, 1, tzinfo=UTC),
        "source": "transfer_probe",
        "action": "attempted",
        "object_type": "question",
        "object_id": "q-1",
        "knowledge_refs": ["kc-1"],
        "outcome": EventOutcome(correctness=True),
        "evaluation_phase": EvaluationPhase.independent_no_ai,
    }
    with pytest.raises(ValidationError):
        LearningEvent.model_validate(base)
    event = LearningEvent.model_validate(
        {
            **base,
            "intervention": {"ai_assisted": False, "independent_mode": True},
        }
    )
    assert event.evaluation_phase == EvaluationPhase.independent_no_ai


def test_unknown_misconception_is_not_invented_from_an_incorrect_answer():
    event = LearningEvent(
        student_id=UUID("11111111-1111-1111-1111-111111111111"),
        occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
        received_at=datetime(2026, 8, 1, tzinfo=UTC),
        source="review",
        action="attempted",
        object_type="question",
        object_id="q-1",
        knowledge_refs=["kc-1"],
        outcome=EventOutcome(correctness=False),
    )
    state = CognitiveStateV2.from_observations(
        student_id=event.student_id,
        knowledge_ref="kc-1",
        events=[event],
        computed_at=event.occurred_at,
    )
    assert state.misconception.active_misconceptions == []
    assert state.misconception.misconception_confidence is None
