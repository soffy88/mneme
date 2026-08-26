"""Registry-aligned, read-only shadow model comparison.

This module is deliberately independent of the database and of the tutoring
control path.  A challenger supplies one causal prediction per evaluation
event; the comparator checks the ModelRegistry-style train/eval window before
computing predictive and calibration metrics.  It never changes learner
state, selects an intervention, or treats an observed metric as causal lift.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

_EPS = 1e-6
_CALIBRATION_BINS = 10


class ShadowEvaluationError(ValueError):
    """Input violates the fail-closed shadow evaluation contract."""


@dataclass(frozen=True, slots=True)
class ShadowPrediction:
    """One prediction made before an observed evaluation event."""

    model_id: str
    occurred_at: datetime
    probability: float
    actual: bool
    student_id: UUID | None = None
    kc_id: str | None = None
    received_at: datetime | None = None
    event_id: UUID | None = None
    subject: str | None = None
    evidence_count: int | None = None
    out_of_distribution: bool | None = None

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ShadowEvaluationError("model_id must not be empty")
        if not math.isfinite(self.probability) or not 0.0 <= self.probability <= 1.0:
            raise ShadowEvaluationError("probability must be finite and in [0, 1]")
        _require_aware("occurred_at", self.occurred_at)
        if self.received_at is not None:
            _require_aware("received_at", self.received_at)
            if self.received_at < self.occurred_at:
                raise ShadowEvaluationError(
                    "received_at cannot precede occurred_at"
                )


def _require_aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ShadowEvaluationError(f"{label} must be timezone-aware")


def _validate_window(
    *,
    train_start: datetime,
    train_end: datetime,
    eval_start: datetime,
    eval_end: datetime,
    as_of: datetime,
) -> None:
    for label, value in (
        ("train_start", train_start),
        ("train_end", train_end),
        ("eval_start", eval_start),
        ("eval_end", eval_end),
        ("as_of", as_of),
    ):
        _require_aware(label, value)
    if train_start >= train_end:
        raise ShadowEvaluationError("train window must have positive duration")
    if train_end > eval_start or eval_start >= eval_end:
        raise ShadowEvaluationError(
            "train/eval windows must be ordered and non-overlapping"
        )
    if eval_end > as_of:
        raise ShadowEvaluationError("evaluation window extends beyond as_of")


def validate_shadow_window(
    *,
    train_start: datetime,
    train_end: datetime,
    eval_start: datetime,
    eval_end: datetime,
    as_of: datetime,
) -> None:
    """Validate a registry-aligned window for an upstream replay adapter."""

    _validate_window(
        train_start=train_start,
        train_end=train_end,
        eval_start=eval_start,
        eval_end=eval_end,
        as_of=as_of,
    )


def _validate_predictions(
    predictions: Sequence[ShadowPrediction],
    *,
    model_id: str,
    eval_start: datetime,
    eval_end: datetime,
    as_of: datetime,
) -> list[ShadowPrediction]:
    selected: list[ShadowPrediction] = []
    for prediction in predictions:
        if prediction.model_id != model_id:
            raise ShadowEvaluationError(
                "all predictions must belong to the requested model_id"
            )
        if not eval_start <= prediction.occurred_at < eval_end:
            raise ShadowEvaluationError(
                "prediction occurred_at must be inside [eval_start, eval_end)"
            )
        if prediction.occurred_at > as_of or (
            prediction.received_at is not None and prediction.received_at > as_of
        ):
            raise ShadowEvaluationError(
                "future occurred_at/received_at is not allowed by as_of"
            )
        selected.append(prediction)
    return selected


def _auc(actuals: Sequence[int], probabilities: Sequence[float]) -> float | None:
    positives = sum(actuals)
    negatives = len(actuals) - positives
    if positives == 0 or negatives == 0:
        return None

    ranked = sorted(zip(probabilities, actuals), key=lambda item: item[0])
    positive_rank_sum = 0.0
    index = 0
    while index < len(ranked):
        end = index + 1
        while end < len(ranked) and ranked[end][0] == ranked[index][0]:
            end += 1
        average_rank = (index + 1 + end) / 2.0
        positive_rank_sum += average_rank * sum(
            actual for _, actual in ranked[index:end]
        )
        index = end
    return (positive_rank_sum - positives * (positives + 1) / 2.0) / (
        positives * negatives
    )


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None and math.isfinite(value) else None


def _sigmoid(value: float) -> float:
    if value >= 0.0:
        exponent = math.exp(-value)
        return 1.0 / (1.0 + exponent)
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


def _calibration_slope(
    actuals: Sequence[int], probabilities: Sequence[float]
) -> float | None:
    """Fit ``logit(y) ~ intercept + slope * logit(prediction)`` via IRLS.

    A slope near 1 means the prediction spread is calibrated.  Degenerate or
    perfectly separated samples have no finite maximum-likelihood slope and
    deliberately return ``None`` instead of reporting an unstable number.
    """

    n = len(actuals)
    positives = sum(actuals)
    if n < 4 or positives == 0 or positives == n:
        return None
    x_values = [
        math.log(probability / (1.0 - probability))
        for probability in probabilities
    ]
    mean_x = sum(x_values) / n
    if sum((value - mean_x) ** 2 for value in x_values) <= 1e-12:
        return None

    base_rate = min(1.0 - _EPS, max(_EPS, positives / n))
    intercept = math.log(base_rate / (1.0 - base_rate))
    slope = 1.0
    for _ in range(50):
        means = [_sigmoid(intercept + slope * value) for value in x_values]
        weights = [max(_EPS, mean * (1.0 - mean)) for mean in means]
        gradient_0 = sum(actual - mean for actual, mean in zip(actuals, means))
        gradient_1 = sum(
            (actual - mean) * value
            for actual, mean, value in zip(actuals, means, x_values)
        )
        hessian_00 = sum(weights)
        hessian_01 = sum(weight * value for weight, value in zip(weights, x_values))
        hessian_11 = sum(
            weight * value * value for weight, value in zip(weights, x_values)
        )
        determinant = hessian_00 * hessian_11 - hessian_01 * hessian_01
        if determinant <= 1e-12:
            return None
        delta_0 = (
            hessian_11 * gradient_0 - hessian_01 * gradient_1
        ) / determinant
        delta_1 = (
            hessian_00 * gradient_1 - hessian_01 * gradient_0
        ) / determinant
        intercept += delta_0
        slope += delta_1
        if abs(delta_0) + abs(delta_1) < 1e-8:
            break
        if abs(intercept) > 100.0 or abs(slope) > 100.0:
            return None
    return slope if math.isfinite(slope) and abs(slope) <= 100.0 else None


def _metrics(predictions: Sequence[ShadowPrediction]) -> dict[str, Any]:
    n = len(predictions)
    if n == 0:
        return {
            "n": 0,
            "base_rate": None,
            "auc": None,
            "logloss": None,
            "brier": None,
            "ece": None,
            "calibration_slope": None,
        }

    actuals = [int(item.actual) for item in predictions]
    probabilities = [item.probability for item in predictions]
    clipped = [min(1.0 - _EPS, max(_EPS, probability)) for probability in probabilities]
    logloss = -sum(
        actual * math.log(probability)
        + (1 - actual) * math.log(1.0 - probability)
        for actual, probability in zip(actuals, clipped)
    ) / n
    brier = sum(
        (probability - actual) ** 2
        for probability, actual in zip(probabilities, actuals)
    ) / n

    counts = [0] * _CALIBRATION_BINS
    probability_sums = [0.0] * _CALIBRATION_BINS
    actual_sums = [0] * _CALIBRATION_BINS
    for probability, actual in zip(probabilities, actuals):
        bucket = min(_CALIBRATION_BINS - 1, int(probability * _CALIBRATION_BINS))
        counts[bucket] += 1
        probability_sums[bucket] += probability
        actual_sums[bucket] += actual
    ece = sum(
        abs(probability_sums[index] / count - actual_sums[index] / count) * count
        for index, count in enumerate(counts)
        if count
    ) / n

    return {
        "n": n,
        "base_rate": round(sum(actuals) / n, 6),
        "auc": _rounded(_auc(actuals, probabilities)),
        "logloss": _rounded(logloss),
        "brier": _rounded(brier),
        "ece": _rounded(ece),
        "calibration_slope": _rounded(_calibration_slope(actuals, probabilities)),
    }


def evaluation_slices(
    predictions: Sequence[ShadowPrediction],
    *,
    train_end: datetime | None = None,
    eval_start: datetime | None = None,
    eval_end: datetime | None = None,
) -> dict[str, list[ShadowPrediction]]:
    """Build deterministic evaluation slices without changing learning paths."""

    ordered = sorted(predictions, key=_event_key)
    slices: dict[str, list[ShadowPrediction]] = {"all": list(ordered)}
    if train_end is not None:
        slices["temporal_train"] = [row for row in ordered if row.occurred_at < train_end]
    if eval_start is not None and eval_end is not None:
        slices["temporal_eval"] = [
            row for row in ordered if eval_start <= row.occurred_at < eval_end
        ]
    if ordered and all(row.student_id is not None for row in ordered):
        slices["student_level_eval"] = [
            row
            for row in ordered
            if int(str(row.student_id).replace("-", "")[-2:], 16) % 5 == 0
        ]
    first_by_student: dict[UUID, datetime] = {}
    for row in ordered:
        if row.student_id is not None:
            first_by_student.setdefault(row.student_id, row.occurred_at)
    slices["cold_start"] = [
        row
        for row in ordered
        if row.student_id is not None and first_by_student[row.student_id] == row.occurred_at
    ]
    slices["warm_start"] = [
        row
        for row in ordered
        if row.student_id is not None and first_by_student[row.student_id] < row.occurred_at
    ]
    slices["ood"] = [row for row in ordered if row.out_of_distribution is True]
    for subject in sorted({row.subject for row in ordered if row.subject}):
        slices[f"subject:{subject}"] = [row for row in ordered if row.subject == subject]
    for label, lower, upper in (("0-1", 0, 1), ("2-4", 2, 4), ("5+", 5, None)):
        slices[f"evidence_count:{label}"] = [
            row
            for row in ordered
            if row.evidence_count is not None
            and row.evidence_count >= lower
            and (upper is None or row.evidence_count <= upper)
        ]
    return slices


def slice_metrics(predictions: Sequence[ShadowPrediction]) -> dict[str, dict[str, Any]]:
    """Return the same AUC/logloss/Brier/ECE contract for every slice."""

    return {name: _metrics(rows) for name, rows in evaluation_slices(predictions).items()}


def _event_key(
    prediction: ShadowPrediction,
) -> tuple[UUID | None, str | None, datetime, UUID | None]:
    return (
        prediction.student_id,
        prediction.kc_id,
        prediction.occurred_at,
        prediction.event_id,
    )


def _compare(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float | None]:
    def gain(metric: str) -> float | None:
        candidate_value = candidate[metric]
        baseline_value = baseline[metric]
        if candidate_value is None or baseline_value is None:
            return None
        return round(baseline_value - candidate_value, 6)

    auc_delta = None
    if candidate["auc"] is not None and baseline["auc"] is not None:
        auc_delta = round(candidate["auc"] - baseline["auc"], 6)
    calibration_slope_error_gain = None
    if (
        candidate["calibration_slope"] is not None
        and baseline["calibration_slope"] is not None
    ):
        calibration_slope_error_gain = round(
            abs(baseline["calibration_slope"] - 1.0)
            - abs(candidate["calibration_slope"] - 1.0),
            6,
        )
    return {
        "auc_delta": auc_delta,
        "logloss_gain": gain("logloss"),
        "brier_gain": gain("brier"),
        "ece_gain": gain("ece"),
        "calibration_slope_error_gain": calibration_slope_error_gain,
    }


def shadow_evaluation_report(
    predictions: Sequence[ShadowPrediction],
    *,
    model_id: str,
    train_start: datetime,
    train_end: datetime,
    eval_start: datetime,
    eval_end: datetime,
    as_of: datetime | None = None,
    baseline: Sequence[ShadowPrediction] | None = None,
    baseline_model_id: str | None = None,
) -> dict[str, Any]:
    """Score a candidate in a registry-aligned window without side effects.

    ``predictions`` must already be causal predictions made before each event.
    The comparator verifies the temporal envelope and, when supplied, requires
    the baseline to be aligned to the exact same event keys.  A returned delta
    is an observed predictive difference, never a causal treatment effect.
    """

    from services.observability import record_shadow_evaluation

    record_shadow_evaluation()
    effective_as_of = as_of or datetime.now(UTC)
    _validate_window(
        train_start=train_start,
        train_end=train_end,
        eval_start=eval_start,
        eval_end=eval_end,
        as_of=effective_as_of,
    )
    candidate_rows = _validate_predictions(
        predictions,
        model_id=model_id,
        eval_start=eval_start,
        eval_end=eval_end,
        as_of=effective_as_of,
    )
    candidate_metrics = _metrics(candidate_rows)

    result: dict[str, Any] = {
        "evaluation_version": "shadow-evaluation/v1",
        "model_id": model_id,
        "mode": "shadow_only",
        "window": {
            "train_start": train_start.isoformat(),
            "train_end": train_end.isoformat(),
            "eval_start": eval_start.isoformat(),
            "eval_end": eval_end.isoformat(),
            "as_of": effective_as_of.isoformat(),
        },
        "candidate": candidate_metrics,
        "slices": slice_metrics(candidate_rows),
        "comparison": None,
        "guardrails": {
            "writes_database": False,
            "controls_learning_path": False,
            "future_events_used": False,
            "causal_effect_claim": False,
        },
    }

    if baseline is None:
        return result
    baseline_id = baseline_model_id or "baseline"
    baseline_rows = _validate_predictions(
        baseline,
        model_id=baseline_id,
        eval_start=eval_start,
        eval_end=eval_end,
        as_of=effective_as_of,
    )
    if len(candidate_rows) != len(baseline_rows) or any(
        _event_key(candidate) != _event_key(reference)
        for candidate, reference in zip(candidate_rows, baseline_rows)
    ):
        raise ShadowEvaluationError(
            "candidate and baseline must be aligned to identical evaluation events"
        )
    baseline_metrics = _metrics(baseline_rows)
    result["baseline"] = {"model_id": baseline_id, **baseline_metrics}
    result["comparison"] = {
        "candidate_vs_baseline": _compare(candidate_metrics, baseline_metrics),
        "interpretation": "observed_predictive_difference; not causal uplift",
    }
    return result
