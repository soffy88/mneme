from datetime import UTC, datetime
from uuid import UUID

from mneme_core.policy_engine import PolicyCandidate, PolicyContext, choose_next_action
from services.policy_trace import PolicyDecision, replay_policy_decision


def test_policy_decision_trace_contains_state_policy_and_evidence_fields():
    sid = UUID("11111111-1111-1111-1111-111111111111")
    candidates = [
        PolicyCandidate(
            "diag",
            "diagnostic",
            5,
            0.2,
            epistemic_uncertainty=0.5,
            evidence_sufficiency=0.1,
            evidence_refs=("event-1",),
            state_version="cognitive-state/v2",
        ),
        PolicyCandidate("review", "review", 5, 0.6, evidence_refs=("event-2",)),
    ]
    core = choose_next_action(candidates, PolicyContext())
    trace = PolicyDecision.from_core(
        student_id=sid,
        candidates=candidates,
        decision=core,
        timestamp=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert trace.state_version == "cognitive-state/v2"
    assert trace.policy_version == "policy/v2"
    assert trace.selected_action is not None
    assert trace.reason_codes
    assert trace.evidence_refs == ["event-1", "event-2"]


def test_policy_replay_is_deterministic_and_never_contains_mastery_writes():
    candidates = [PolicyCandidate("a", "review", 5, 0.5)]
    left = replay_policy_decision(candidates, PolicyContext())
    right = replay_policy_decision(candidates, PolicyContext())
    assert left == right
    assert not hasattr(left, "p_mastery")
