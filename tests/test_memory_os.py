from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from mneme_core.policy_engine import (
    PolicyCandidate,
    PolicyContext,
    choose_next_action,
)
from services.evaluation_os import (
    EvaluationObservation,
    evaluation_report,
    uplift_metric,
)
from services.evidence_graph import claim_evidence_payload, redact_event_for_parent
from services.learner_state_service import compose_learner_state, term_window
from services.models import MemoryClaim, MemoryClaimEvidence, MemoryEvidence
from services.policy_service import candidates_from_plan


def _mastery(kc: str, p: float = 0.55):
    return SimpleNamespace(
        knowledge_point=kc,
        p_mastery=p,
        long_term_mastery=p,
        p_recognition=0.4,
        p_recognition_init=0.2,
        fsrs_card_json=None,
        n_attempts=2,
        mastery_confirmed=False,
        last_interaction_at=None,
    )


def _event(kc: str, *, correct: bool, confidence: float | None = None):
    return SimpleNamespace(
        id=uuid4(),
        knowledge_point=kc,
        is_correct=correct,
        predicted_confidence=confidence,
        source="review",
        time_spent_seconds=20,
    )


def test_learner_state_v2_is_interpretable_and_read_only():
    student_id = UUID("11111111-1111-1111-1111-111111111111")
    state = compose_learner_state(
        [_mastery("kc-1")],
        [_event("kc-1", correct=True, confidence=0.8), _event("kc-1", correct=False, confidence=0.7)],
        student_id=student_id,
        now=datetime(2026, 8, 24, tzinfo=UTC),
    )

    item = state["knowledge_points"]["kc-1"]
    assert state["state_version"] == "learner-state/v2"
    assert item["mastery"]["p_mastery"] == 0.55
    assert item["metacognition"]["n"] == 2
    assert item["uncertainty"]["standard_error"] > 0
    assert state["summary"]["evidence_event_count"] == 2


def test_term_window_is_deterministic():
    start, end = term_window("2026-Q3")
    assert start.isoformat() == "2026-07-01T00:00:00+00:00"
    assert end.isoformat() == "2026-10-01T00:00:00+00:00"


def test_policy_is_stable_and_prefers_due_gain_per_minute():
    candidates = [
        PolicyCandidate("new", "new_learn", 20, 0.9),
        PolicyCandidate("due", "review", 5, 0.6, due_urgency=1.0),
    ]
    decision = choose_next_action(candidates, PolicyContext())
    assert decision.candidate_id == "due"
    assert decision.objective == "expected_learning_gain_per_minute"
    assert decision.reason


def test_policy_service_prefers_explicit_candidate_signals_over_type_defaults():
    candidates = candidates_from_plan(
        [
            {
                "type": "review",
                "ku_ids": ["kc-1"],
                "estimated_minutes": 5,
                "expected_learning_gain": 0.91,
                "item_difficulty": 0.82,
                "due_urgency": 0.2,
                "exam_relevance": 0.1,
                "learner_choice": 0.7,
            }
        ],
        mastery_by_kc={"kc-1": 0.6},
    )

    candidate = candidates[0]
    assert candidate.expected_gain == 0.91
    assert candidate.item_difficulty == 0.82
    assert candidate.due_urgency == 0.2
    assert candidate.learner_choice == 0.7


def test_evaluation_os_returns_null_uplift_without_two_arms():
    sid = UUID("22222222-2222-2222-2222-222222222222")
    row = EvaluationObservation(
        sid,
        datetime(2026, 8, 1, tzinfo=UTC),
        True,
        "review",
        treatment="control",
    )
    assert uplift_metric([row])["value"] is None
    report = evaluation_report(
        [row], now=datetime(2026, 8, 20, tzinfo=UTC)
    )
    assert report["n_students"] == 1
    assert report["guardrails"]["no_student_ids_in_output"] is True


def test_evaluation_os_observed_uplift_and_parent_redaction():
    sid = UUID("33333333-3333-3333-3333-333333333333")
    rows = [
        EvaluationObservation(
            sid, datetime(2026, 8, 1, tzinfo=UTC), True, "review", "worked_example"
        ),
        EvaluationObservation(
            sid, datetime(2026, 8, 2, tzinfo=UTC), False, "review", "control"
        ),
    ]
    assert uplift_metric(rows)["value"] == 1.0
    redacted = redact_event_for_parent(
        {"response": {"answer": "x"}, "process_signals": {"latency_ms": 1}}
    )
    assert redacted["response"] is None
    assert redacted["process_signals"] == {}


def test_claim_evidence_payload_preserves_provenance():
    claim_id = uuid4()
    evidence_id = uuid4()
    claim = MemoryClaim(
        id=claim_id,
        student_id=uuid4(),
        claim_type="growth",
        subject_type="knowledge_point",
        subject_id="kc-1",
        claim_text="近期检索更稳定",
        confidence=0.8,
        model_version="test",
        privacy_class="P1",
        provenance={"rule": "retention_delta"},
    )
    evidence = MemoryEvidence(
        id=evidence_id,
        student_id=claim.student_id,
        source_event_id=uuid4(),
        evidence_type="learning_event_v2",
        occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
        payload={"outcome": {"correctness": True}},
        provenance={"source": "test"},
        privacy_class="P1",
    )
    payload = claim_evidence_payload(
        claim,
        [(
            MemoryClaimEvidence(
                claim_id=claim_id, evidence_id=evidence_id, relation="supports"
            ),
            evidence,
        )],
    )
    assert payload["claim"]["confidence"] == 0.8
    assert payload["evidence"][0]["relation"] == "supports"
