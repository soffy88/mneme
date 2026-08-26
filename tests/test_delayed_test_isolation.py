from datetime import UTC, datetime
from uuid import UUID

from services.evaluation_os import EvaluationObservation, delayed_gain_metric


def test_delayed_endpoint_requires_same_student_baseline_pair():
    sid = UUID("11111111-1111-1111-1111-111111111111")
    delayed_only = EvaluationObservation(
        sid,
        datetime(2026, 8, 8, tzinfo=UTC),
        True,
        "transfer_probe",
        evaluation_phase="delayed",
    )
    assert delayed_gain_metric([delayed_only])["value"] is None
    baseline = EvaluationObservation(
        sid,
        datetime(2026, 8, 1, tzinfo=UTC),
        False,
        "transfer_probe",
        evaluation_phase="baseline",
    )
    assert delayed_gain_metric([baseline, delayed_only])["value"] == 1.0
