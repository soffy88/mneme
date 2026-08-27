from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from event_schema import EvaluationPhase, EventOutcome, EventProvenance, LearningEvent, ProcessSignals

from services.policy_trace import PolicyDecision
from services.product_closure import (
    ContaminationStatus,
    EvidenceMode,
    FakeBillingProvider,
    FirstValueStage,
    ProductEventType,
    ReturnReason,
    advance_first_value_state,
    build_learn_now,
    build_notification_contract,
    build_session_summary,
    build_today_queue,
    check_entitlement,
    claim_guard_product,
    compute_cohort_analytics,
    compute_commercial_metrics,
    compute_flywheel_health,
    compute_product_analytics,
    create_product_learning_event,
    get_return_reason,
    link_policy_outcome,
    memory_label,
    project_memory,
    project_misconceptions,
    project_outcome_ledger,
    project_progress,
    shadow_feedback_contract,
)


BASE = datetime(2026, 1, 1, tzinfo=UTC)
SID = UUID("11111111-1111-1111-1111-111111111111")


def event(
    *,
    at: datetime = BASE,
    action: str = "attempted",
    event_id: UUID | None = None,
    outcome: EventOutcome | None = EventOutcome(correctness=True),
    phase: str | None = None,
    synthetic: bool = False,
    active_seconds: float | None = None,
) -> LearningEvent:
    metadata = {"synthetic": True} if synthetic else {}
    process = ProcessSignals(active_learning_seconds=active_seconds)
    intervention = None
    if phase == "independent_no_ai":
        intervention = {"ai_assisted": False, "independent_mode": True}
    return LearningEvent(
        event_id=event_id or uuid4(),
        student_id=SID,
        actor_id=SID,
        occurred_at=at,
        source="quiz",
        action=action,
        object_type="question",
        object_id="q-1",
        knowledge_refs=["ku-1"],
        outcome=outcome,
        process_signals=process,
        evaluation_phase=EvaluationPhase(phase) if phase is not None else None,
        intervention=intervention,
        provenance=EventProvenance(metadata=metadata),
    )


def test_first_value_state_machine():
    rows = [
        create_product_learning_event(
            student_id=SID,
            event_type=ProductEventType.CONTENT_READY,
            occurred_at=BASE,
        ),
        event(at=BASE + timedelta(seconds=30)),
    ]
    state = advance_first_value_state(rows, cognitive_state_available=True, policy_decision_available=True)
    assert state.stage == FirstValueStage.FIRST_VALUE_COMPLETE
    assert state.time_to_first_value_seconds == 30


def test_first_value_requires_real_event():
    synthetic = create_product_learning_event(
        student_id=SID,
        event_type=ProductEventType.CONTENT_READY,
        occurred_at=BASE,
        synthetic=True,
    )
    state = advance_first_value_state([synthetic], cognitive_state_available=True, policy_decision_available=True)
    assert state.stage == FirstValueStage.NEW
    assert state.time_to_first_value_seconds is None


def test_learn_now_uses_policy_decision():
    decision = PolicyDecision(
        student_id=SID,
        timestamp=BASE,
        candidate_actions=[{"candidate_id": "review:math:0", "action": "review"}],
        selected_action={"candidate_id": "review:math:0", "action": "review"},
        reason_codes=["retrieval_urgency"],
        state_version="cognitive-state/v2",
        policy_version="policy/v2",
        evidence_refs=["event-1"],
        constraints={},
    )
    view = build_learn_now(decision)
    assert view.status == "READY"
    assert view.selected_action == decision.selected_action
    assert view.reason_codes == ["retrieval_urgency"]


def test_frontend_cannot_compute_mastery():
    page = Path("apps/mneme-studio/app/learn/page.tsx").read_text(encoding="utf-8")
    assert "Math.round((mastery" not in page
    assert "<OProgress" not in page


def test_why_this_uses_real_evidence():
    decision = PolicyDecision(
        student_id=SID,
        timestamp=BASE,
        candidate_actions=[],
        selected_action={"candidate_id": "x"},
        reason_codes=["evidence_gap"],
        state_version="cognitive-state/v2",
        policy_version="policy/v2",
        evidence_refs=["event-1"],
        constraints={},
    )
    view = build_learn_now(
        decision,
        [{"claim_type": "memory", "claim_value": "fading", "evidence_refs": ["event-1"]},
         {"claim_type": "unrelated", "claim_value": "x", "evidence_refs": ["event-2"]}],
    )
    assert len(view.why_this) == 1
    assert view.why_this[0]["evidence_refs"] == ["event-1"]


def test_today_uses_policy():
    decision = PolicyDecision(
        student_id=SID,
        timestamp=BASE,
        candidate_actions=[{"candidate_id": "b"}, {"candidate_id": "a"}],
        selected_action={"candidate_id": "b"},
        reason_codes=[],
        state_version="cognitive-state/v2",
        policy_version="policy/v2",
        evidence_refs=[],
        constraints={},
    )
    queue = build_today_queue([{"candidate_id": "a"}, {"candidate_id": "b"}], decision)
    assert [row["candidate_id"] for row in queue.tasks] == ["b", "a"]
    assert build_today_queue([], decision).message == "You're caught up"


def test_memory_unknown_not_fake_precision():
    state = {"mastery_probability": 0.73, "mastery_confidence": None}
    assert memory_label(state) == "Unknown"
    projection = project_memory(state, knowledge_ref="ku-1")
    assert projection.label == "Unknown"
    assert projection.details is None


def test_misconception_requires_evidence():
    assert project_misconceptions([{"claim_type": "misconception", "knowledge_ref": "ku-1"}]) == []
    items = project_misconceptions([{
        "claim_type": "misconception",
        "knowledge_ref": "ku-1",
        "confidence": 0.55,
        "claim_value": {"observed_pattern": "same sign error"},
        "evidence_refs": ["event-1"],
    }])
    assert items[0].label == "Possible misconception"
    assert items[0].supporting_evidence == ["event-1"]


def test_activity_not_learning_progress():
    result = project_progress([event(active_seconds=None)], {})
    assert result.activity_progress["active_minutes"] is None
    assert result.learning_progress["long_term_retention_label"] == "Long-term retention not measured yet."
    assert "streak" not in result.activity_progress


def test_session_summary_evidence_grounded():
    result = build_session_summary([event()])
    assert result.what_improved == ["successful response observed"]
    assert len(result.evidence_refs) == 1


def test_return_reason_no_fake_urgency():
    result = get_return_reason(events=[])
    assert result.reason == ReturnReason.NONE
    notification = build_notification_contract(result)
    assert notification.enabled is False
    assert notification.should_send is False


def test_notification_default_off():
    result = get_return_reason(events=[event(action="learning_session_started")])
    notification = build_notification_contract(result, notifications_enabled=True)
    assert notification.should_send is False


def test_flywheel_health():
    first = event(event_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))
    report = compute_flywheel_health(
        interactions=[first],
        events=[first],
        states=[{"evidence_refs": [str(first.event_id)]}],
        policy_decisions=[{"evidence_refs": [str(first.event_id)]}],
        outcome_links=[{"eligible_for_evaluation": True}],
        model_evaluations=[{"model_id": "shadow-1"}],
    )
    assert report.status == "READY"
    assert report.usable_evidence_rate == 1.0
    assert report.n_usable_evidence == 1


def test_usable_evidence_rate():
    clean = event()
    incomplete = event(outcome=None)
    report = compute_flywheel_health(interactions=[clean, incomplete], events=[clean, incomplete])
    assert report.usable_evidence_rate == 0.5


def test_policy_outcome_link():
    decision_id = uuid4()
    action_id = uuid4()
    outcome_id = uuid4()
    decision = {"decision_id": decision_id, "student_id": SID}
    action = event(event_id=action_id, outcome=None)
    outcome = event(event_id=outcome_id, at=BASE + timedelta(seconds=12))
    link = link_policy_outcome(decision=decision, action_event=action, outcome_event=outcome, contamination_status=ContaminationStatus.CLEAN, eligible_for_evaluation=True)
    assert link.latency_seconds == 12
    assert link.eligible_for_evaluation is True


def test_outcome_ledger_projection():
    decision_id = uuid4()
    action_id = uuid4()
    outcome_id = uuid4()
    action = event(event_id=action_id, outcome=None)
    outcome = event(event_id=outcome_id)
    link = {
        "decision_id": decision_id,
        "action_event_id": action_id,
        "outcome_event_id": outcome_id,
        "contamination_status": "CLEAN",
    }
    rows = project_outcome_ledger(
        decisions=[{"decision_id": decision_id, "state_version": "cognitive-state/v2", "policy_version": "policy/v2"}],
        action_events=[action],
        outcome_events=[outcome],
        links=[link],
    )
    assert len(rows) == 1
    assert rows[0].knowledge_ref == "ku-1"


def test_shadow_feedback_no_auto_promote():
    contract = shadow_feedback_contract([{"ledger_id": str(uuid4())}])
    assert contract["mode"] == "shadow_only"
    assert contract["auto_promote"] is False
    assert contract["promotion_requires_model_registry"] is True


def test_product_retention_not_learning_retention():
    rows = [
        create_product_learning_event(student_id=SID, event_type=ProductEventType.LEARNING_SESSION_STARTED, occurred_at=BASE),
        create_product_learning_event(student_id=SID, event_type=ProductEventType.LEARNING_SESSION_STARTED, occurred_at=BASE + timedelta(days=1)),
    ]
    report = compute_product_analytics(rows)
    assert report.d1_return == 1.0
    assert report.learning_outcomes == {}
    assert "not learning retention" in report.product_retention_note.lower()


def test_cohort_no_real_data_semantics():
    report = compute_cohort_analytics([])
    assert report.status == "NO REAL USER DATA"
    assert report.d1 is None and report.d7 is None and report.d30 is None


def test_entitlement_server_side():
    user = {"subscription": {"plan": "PRO", "status": "ACTIVE"}}
    assert check_entitlement(user, "advanced_analytics").allowed is True
    assert check_entitlement(user, "learn_now").allowed is True


def test_entitlement_fail_closed():
    assert check_entitlement({}, "advanced_analytics").allowed is False
    assert check_entitlement({"subscription": {"plan": "PRO", "status": "CANCELED"}}, "advanced_analytics").allowed is False
    assert check_entitlement({"subscription": {"plan": "PRO", "status": "ACTIVE", "current_period_end": (BASE - timedelta(seconds=1)).isoformat()}}, "advanced_analytics", now=BASE).allowed is False
    assert check_entitlement({"subscription": {"plan": "PRO", "status": "ACTIVE"}}, "unknown_capability").allowed is False


@pytest.mark.asyncio
async def test_fake_billing_not_production(monkeypatch):
    monkeypatch.setenv("MNEME_ENV", "prod")
    with pytest.raises(RuntimeError):
        FakeBillingProvider()


def test_no_commercial_evidence_semantics():
    report = compute_commercial_metrics([])
    assert report.status == "NO COMMERCIAL EVIDENCE"
    assert report.mrr is None


def test_demo_excluded_from_evaluation():
    demo = event(synthetic=True)
    report = compute_flywheel_health(interactions=[demo], events=[demo])
    assert report.status == "NO_DATA"
    assert report.usable_evidence_rate is None
    product = compute_product_analytics([demo])
    assert product.evidence_mode == EvidenceMode.NO_DATA


def test_demo_excluded_from_commercial_metrics():
    report = compute_commercial_metrics([{"synthetic": True, "amount": 100}])
    assert report.status == "NO COMMERCIAL EVIDENCE"


def test_claim_guard():
    assert claim_guard_product("Mneme improves learning")["allowed"] is False
    assert claim_guard_product("Mneme improves learning", evidence_mode=EvidenceMode.REAL)["allowed"] is False
