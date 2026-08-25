"""Registry-aligned shadow comparison must fail closed on time leakage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import math

import pytest

from services.shadow_evaluation import (
    ShadowEvaluationError,
    ShadowPrediction,
    shadow_evaluation_report,
)


BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _prediction(
    model_id: str,
    offset_days: int,
    probability: float,
    actual: bool,
    *,
    received_offset_days: int | None = None,
) -> ShadowPrediction:
    occurred_at = BASE + timedelta(days=offset_days)
    received_at = (
        occurred_at + timedelta(days=received_offset_days)
        if received_offset_days is not None
        else None
    )
    return ShadowPrediction(
        model_id=model_id,
        occurred_at=occurred_at,
        probability=probability,
        actual=actual,
        received_at=received_at,
    )


def _report(predictions, *, baseline=None, as_of=BASE + timedelta(days=20)):
    return shadow_evaluation_report(
        predictions,
        model_id="challenger-1",
        train_start=BASE,
        train_end=BASE + timedelta(days=5),
        eval_start=BASE + timedelta(days=5),
        eval_end=BASE + timedelta(days=15),
        as_of=as_of,
        baseline=baseline,
        baseline_model_id="kernel-1" if baseline is not None else None,
    )


def test_shadow_report_is_read_only_and_reports_calibration_metrics() -> None:
    candidate = [
        _prediction("challenger-1", 6, 0.9, True),
        _prediction("challenger-1", 7, 0.1, False),
        _prediction("challenger-1", 8, 0.8, True),
        _prediction("challenger-1", 9, 0.2, False),
    ]
    baseline = [
        _prediction("kernel-1", 6, 0.6, True),
        _prediction("kernel-1", 7, 0.4, False),
        _prediction("kernel-1", 8, 0.6, True),
        _prediction("kernel-1", 9, 0.4, False),
    ]

    result = _report(candidate, baseline=baseline)

    assert result["evaluation_version"] == "shadow-evaluation/v1"
    assert result["mode"] == "shadow_only"
    assert result["candidate"]["n"] == 4
    assert result["candidate"]["auc"] == 1.0
    assert result["candidate"]["brier"] is not None
    assert result["candidate"]["ece"] is not None
    assert "calibration_slope" in result["candidate"]
    assert result["comparison"]["candidate_vs_baseline"]["auc_delta"] == 0.0
    assert "calibration_slope_error_gain" in result["comparison"]["candidate_vs_baseline"]
    assert result["guardrails"] == {
        "writes_database": False,
        "controls_learning_path": False,
        "future_events_used": False,
        "causal_effect_claim": False,
    }


def test_shadow_report_computes_finite_calibration_slope() -> None:
    rows = [
        _prediction("challenger-1", day, probability, actual)
        for day, probability, actual in (
            (6, 0.1, False),
            (7, 0.1, True),
            (8, 0.3, False),
            (9, 0.3, True),
            (10, 0.7, True),
            (11, 0.7, False),
            (12, 0.9, True),
            (13, 0.9, False),
        )
    ]

    result = _report(rows)

    slope = result["candidate"]["calibration_slope"]
    assert slope is not None and math.isfinite(slope)


def test_shadow_report_rejects_future_event_and_future_receipt() -> None:
    future_event = [_prediction("challenger-1", 16, 0.5, True)]
    with pytest.raises(ShadowEvaluationError, match="inside"):
        _report(future_event)

    future_receipt = [
        _prediction(
            "challenger-1",
            6,
            0.5,
            True,
            received_offset_days=30,
        )
    ]
    with pytest.raises(ShadowEvaluationError, match="future"):
        _report(future_receipt)


def test_shadow_report_rejects_model_mixing_and_misaligned_baseline() -> None:
    candidate = [_prediction("wrong-model", 6, 0.5, True)]
    with pytest.raises(ShadowEvaluationError, match="model_id"):
        _report(candidate)

    candidate = [_prediction("challenger-1", 6, 0.5, True)]
    baseline = [_prediction("kernel-1", 7, 0.5, True)]
    with pytest.raises(ShadowEvaluationError, match="identical evaluation events"):
        _report(candidate, baseline=baseline)


def test_shadow_prediction_rejects_naive_or_invalid_probability() -> None:
    with pytest.raises(ShadowEvaluationError, match="timezone-aware"):
        ShadowPrediction(
            model_id="challenger-1",
            occurred_at=datetime(2026, 1, 7),
            probability=0.5,
            actual=True,
        )
    with pytest.raises(ShadowEvaluationError, match=r"\[0, 1\]"):
        ShadowPrediction(
            model_id="challenger-1",
            occurred_at=BASE + timedelta(days=6),
            probability=1.1,
            actual=True,
        )
