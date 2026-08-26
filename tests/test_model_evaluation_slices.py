from datetime import UTC, datetime
from uuid import UUID

from services.shadow_evaluation import ShadowPrediction, evaluation_slices, slice_metrics


def test_shadow_evaluation_exposes_required_slices():
    rows = [
        ShadowPrediction(
            "model/1",
            datetime(2026, 8, 1, tzinfo=UTC),
            0.2,
            False,
            student_id=UUID("00000000-0000-0000-0000-000000000001"),
            subject="math",
            evidence_count=1,
        ),
        ShadowPrediction(
            "model/1",
            datetime(2026, 8, 2, tzinfo=UTC),
            0.8,
            True,
            student_id=UUID("00000000-0000-0000-0000-000000000001"),
            subject="math",
            evidence_count=8,
            out_of_distribution=True,
        ),
    ]
    slices = evaluation_slices(rows)
    assert {"cold_start", "warm_start", "ood", "subject:math", "evidence_count:0-1", "evidence_count:5+"} <= set(slices)
    assert set(slice_metrics(rows)["all"]) >= {"auc", "logloss", "brier", "ece", "calibration_slope"}
