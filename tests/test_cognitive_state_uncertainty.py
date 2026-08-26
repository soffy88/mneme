from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from event_schema import EventOutcome, LearningEvent
from services.cognitive_state_v2 import CognitiveStateV2


def _event(i: int) -> LearningEvent:
    when = datetime(2026, 8, i, tzinfo=UTC)
    return LearningEvent(
        event_id=UUID(f"00000000-0000-0000-0000-{i:012d}"),
        student_id=UUID("11111111-1111-1111-1111-111111111111"),
        occurred_at=when,
        received_at=when,
        source="review",
        action="attempted",
        object_type="question",
        object_id=f"q-{i}",
        knowledge_refs=["kc-1"],
        outcome=EventOutcome(correctness=True),
    )


def test_uncertainty_decreases_with_more_evidence_without_changing_kernel_value():
    sid = UUID("11111111-1111-1111-1111-111111111111")
    mastery = SimpleNamespace(p_mastery=0.72, n_attempts=2, fsrs_card_json=None)
    low = CognitiveStateV2.from_observations(
        student_id=sid,
        knowledge_ref="kc-1",
        events=[_event(1), _event(2)],
        mastery=mastery,
        computed_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    high = CognitiveStateV2.from_observations(
        student_id=sid,
        knowledge_ref="kc-1",
        events=[_event(i) for i in range(1, 11)],
        mastery=SimpleNamespace(p_mastery=0.72, n_attempts=10, fsrs_card_json=None),
        computed_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert low.knowledge.mastery_probability == high.knowledge.mastery_probability
    assert low.uncertainty.epistemic_uncertainty > high.uncertainty.epistemic_uncertainty
    assert low.uncertainty.evidence_sufficiency < high.uncertainty.evidence_sufficiency
