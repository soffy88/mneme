from services.observability import (
    increment_metric,
    metrics_snapshot,
    record_cognitive_projection,
    record_learning_event_ingest,
    record_policy_decision,
    record_shadow_evaluation,
    reset_metrics,
)


def test_cognitive_closure_metrics_have_stable_names_and_no_payloads():
    reset_metrics()
    record_learning_event_ingest(projection_lag_ms=12)
    record_cognitive_projection(evidence_sufficient=False)
    record_policy_decision(fallback=True)
    record_shadow_evaluation()
    increment_metric("custom_contract_metric")

    counters = metrics_snapshot()["counters"]
    assert counters["learning_event_ingest_total"] == 1
    assert counters["learning_event_projection_lag"] == 12
    assert counters["cognitive_projection_failures"] == 0
    assert counters["policy_decision_total"] == 1
    assert counters["policy_fallback_total"] == 1
    assert counters["model_shadow_eval_total"] == 1
    assert counters["evidence_insufficient_total"] == 1
    assert "student_id" not in str(counters)
