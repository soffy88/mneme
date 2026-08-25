from __future__ import annotations

from services.observability import (
    accept_trace_id,
    metrics_snapshot,
    new_trace_id,
    record_request,
    reset_metrics,
    route_template,
)


def test_trace_ids_are_bounded_and_invalid_values_are_replaced() -> None:
    assert accept_trace_id("trace-123") == "trace-123"
    generated = accept_trace_id("bad value with spaces")
    assert generated != "bad value with spaces"
    assert len(generated) == 32
    assert len(new_trace_id()) == 32


def test_metrics_are_aggregate_and_use_route_templates() -> None:
    reset_metrics()
    record_request("get", "/v2/learner-state/{student_id}", 200, 10.0)
    record_request("GET", "/v2/learner-state/{student_id}", 503, 20.0)

    snapshot = metrics_snapshot()
    endpoint = snapshot["endpoints"]["GET /v2/learner-state/{student_id}"]
    assert snapshot["schema_version"] == "mneme-observability/v1"
    assert endpoint["requests_total"] == 2
    assert endpoint["errors_total"] == 1
    assert endpoint["latency_ms_p95"] == 20.0
    assert "student-id-value" not in str(snapshot)


def test_route_template_falls_back_without_leaking_url_parameters() -> None:
    assert route_template({}, "/v2/events/secret-student-id") == "/unknown"
