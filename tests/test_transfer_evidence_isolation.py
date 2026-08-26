from datetime import UTC, datetime, timedelta
from uuid import UUID

from event_schema import EventOutcome, EvaluationPhase, LearningEvent
from services.cognitive_state_v2 import CognitiveStateV2


def _event(index: int, phase: str | None, correct: bool):
    when = datetime(2026, 8, 1, tzinfo=UTC) + timedelta(days=index)
    return LearningEvent(
        student_id=UUID("11111111-1111-1111-1111-111111111111"),
        occurred_at=when,
        received_at=when,
        source="transfer_probe" if phase else "practice",
        action="attempted",
        object_type="question",
        object_id=f"q-{index}",
        knowledge_refs=["kc-1"],
        outcome=EventOutcome(correctness=correct),
        evaluation_phase=EvaluationPhase(phase) if phase else None,
        intervention=(
            {"ai_assisted": False, "independent_mode": True}
            if phase == "independent_no_ai"
            else None
        ),
    )


def test_practice_events_do_not_update_transfer_dimensions():
    state = CognitiveStateV2.from_observations(
        student_id=UUID("11111111-1111-1111-1111-111111111111"),
        knowledge_ref="kc-1",
        events=[_event(0, None, True), _event(1, "near_transfer", True), _event(2, "far_transfer", False)],
        computed_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    assert state.transfer.near_transfer == 1.0
    assert state.transfer.far_transfer == 0.0
    assert state.transfer.transfer_evidence_count == 2
