from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from event_schema import EventOutcome, LearningEvent, MetacognitiveSignals
from services.cognitive_state_v2 import CognitiveStateV2


SID = UUID("11111111-1111-1111-1111-111111111111")
BASE = datetime(2026, 8, 1, tzinfo=UTC)


def _event(index: int, *, correct: bool = True, phase: str | None = None, **kwargs):
    values = {
        "event_id": UUID(f"00000000-0000-0000-0000-{index:012d}"),
        "student_id": SID,
        "occurred_at": BASE + timedelta(days=index),
        "received_at": BASE + timedelta(days=index),
        "source": "review",
        "action": "attempted",
        "object_type": "question",
        "object_id": f"q-{index}",
        "knowledge_refs": ["kc-1"],
        "outcome": EventOutcome(correctness=correct),
    }
    if phase is not None:
        values["evaluation_phase"] = phase
    values.update(kwargs)
    return LearningEvent.model_validate(values)


def _mastery(p: float = 0.72, n: int = 2):
    return SimpleNamespace(
        p_mastery=p,
        n_attempts=n,
        p_recognition=0.61,
        fsrs_card_json=None,
    )


def test_cognitive_state_v2_has_one_typed_multidimensional_contract():
    state = CognitiveStateV2.from_observations(
        student_id=SID,
        knowledge_ref="kc-1",
        events=[_event(1), _event(2, correct=False)],
        mastery=_mastery(),
        computed_at=BASE + timedelta(days=2),
    )

    assert state.identity.state_version == "cognitive-state/v2"
    assert state.knowledge.mastery_probability == 0.72
    assert state.knowledge.evidence_count == 2
    assert state.memory.retrievability is None
    assert state.recognition.recognition_probability == 0.61
    assert state.transfer.transfer_evidence_count == 0
    assert state.provenance.evidence_event_ids
    assert {claim.claim_type for claim in state.evidence_claims} >= {
        "mastery_probability",
        "retrievability",
    }


def test_state_does_not_treat_a_prior_without_events_as_student_evidence():
    state = CognitiveStateV2.from_observations(
        student_id=SID,
        knowledge_ref="kc-1",
        events=[],
        mastery=_mastery(p=0.2, n=0),
        computed_at=BASE,
    )

    assert state.knowledge.mastery_probability is None
    assert state.knowledge.evidence_count == 0
    assert state.knowledge.mastery_confidence is None
    assert state.uncertainty.epistemic_uncertainty is None
    assert state.uncertainty.evidence_sufficiency is None
    mastery_claim = next(
        claim for claim in state.evidence_claims if claim.claim_type == "mastery_probability"
    )
    assert mastery_claim.claim_value is None
    assert mastery_claim.evidence_refs == []


def test_same_events_same_versions_are_replay_deterministic():
    events = [_event(1), _event(2, correct=False)]
    left = CognitiveStateV2.from_observations(
        student_id=SID,
        knowledge_ref="kc-1",
        events=events,
        mastery=_mastery(),
        computed_at=BASE + timedelta(days=2),
        input_checksum="input",
        projection_checksum="projection",
    )
    right = CognitiveStateV2.from_observations(
        student_id=SID,
        knowledge_ref="kc-1",
        events=list(reversed(events)),
        mastery=_mastery(),
        computed_at=BASE + timedelta(days=2),
        input_checksum="input",
        projection_checksum="projection",
    )

    assert left.model_dump(mode="json") == right.model_dump(mode="json")
    assert left.compare(right)["changed_dimensions"] == []


def test_metacognitive_text_alone_does_not_create_numeric_evidence():
    event = _event(
        1,
        response={"self_explanation": "我先找出已知条件"},
        metacognitive=MetacognitiveSignals(),
    )
    state = CognitiveStateV2.from_observations(
        student_id=SID,
        knowledge_ref="kc-1",
        events=[event],
        mastery=_mastery(n=1),
        computed_at=BASE,
    )

    assert state.metacognition.self_explanation_quality is None
    assert state.metacognition.jol_calibration is None
