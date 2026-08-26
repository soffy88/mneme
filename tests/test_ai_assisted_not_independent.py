from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from event_schema import EventOutcome, EvaluationPhase, LearningEvent, is_independent_no_ai_event


def _event(*, ai_assisted: bool, independent_mode: bool):
    return LearningEvent(
        student_id=UUID("11111111-1111-1111-1111-111111111111"),
        occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
        received_at=datetime(2026, 8, 1, tzinfo=UTC),
        source="transfer_probe",
        action="attempted",
        object_type="question",
        object_id="q-1",
        knowledge_refs=["kc-1"],
        outcome=EventOutcome(correctness=True),
        evaluation_phase=EvaluationPhase.independent_no_ai,
        intervention={"ai_assisted": ai_assisted, "independent_mode": independent_mode},
    )


def test_ai_assisted_event_is_never_independent_mastery_evidence():
    with pytest.raises(ValidationError):
        _event(ai_assisted=True, independent_mode=False)
    clean = _event(ai_assisted=False, independent_mode=True)
    assert is_independent_no_ai_event(clean)
