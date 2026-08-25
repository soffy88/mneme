from services.grading_observability import (
    grading_snapshot,
    record_grading,
    reset_grading_metrics,
)


def test_grading_snapshot_reports_aggregate_coverage_only() -> None:
    reset_grading_metrics()
    record_grading("solve", "sympy")
    record_grading("solve", "plain_fallback", fallback_reason="parse_failure")
    record_grading("open", "needs_qualitative", fallback_reason="verifier_unavailable")
    record_grading("short", "objective_deterministic", kernel_disagreement=True)

    snapshot = grading_snapshot()
    assert snapshot["total"] == 4
    assert snapshot["deterministic"] == 2
    assert snapshot["fallback"] == 2
    assert snapshot["disagreements"] == 1
    assert snapshot["deterministic_coverage"] == 0.5
    assert "parse_failure" not in str(snapshot)
    assert "student_id" not in str(snapshot)
