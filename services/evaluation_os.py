"""Evaluation OS primitives for retention, transfer and policy uplift.

All metrics are time-aware, aggregate-only, and return ``None`` when a sample
does not support a conclusion.  They are suitable for shadow/A-B reports but do
not claim causal uplift unless treatment and control are both observed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.experiment_service import student_arm
from services.models import InteractionEvent, InteractionSource


@dataclass(frozen=True, slots=True)
class EvaluationObservation:
    student_id: UUID
    occurred_at: datetime
    is_correct: bool
    source: str
    treatment: str | None = None
    time_spent_seconds: float | None = None
    tutor_mode: str | None = None
    ai_assisted: bool | None = None
    independent_mode: bool | None = None
    evaluation_phase: str | None = None
    received_at: datetime | None = None
    event_id: UUID | None = None
    knowledge_ref: str | None = None
    protocol_version: str | None = None
    active_learning_seconds: float | None = None
    idle_seconds: float | None = None
    background_seconds: float | None = None
    upload_processing_seconds: float | None = None
    ai_latency_seconds: float | None = None
    system_wait_seconds: float | None = None
    baseline_mastery: float | None = None
    retained_mastery: float | None = None
    retained_mastery_gain: float | None = None
    jol_confidence: float | None = None
    jol_at: datetime | None = None
    outcome_revealed_at: datetime | None = None
    assistance_requested: bool = False
    answer_exposed: bool = False
    solution_revealed: bool = False
    hints_used: int = 0


def _interval(successes: int, n: int) -> dict[str, float | int | None]:
    if n <= 0:
        return {"value": None, "n": 0, "lower_95": None, "upper_95": None}
    p = successes / n
    # Wilson interval: stable for small cohorts and deterministic.
    z = 1.96
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    radius = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return {
        "value": round(p, 6),
        "n": n,
        "lower_95": round(max(0.0, centre - radius), 6),
        "upper_95": round(min(1.0, centre + radius), 6),
    }


def retention_at_horizon(
    observations: Iterable[EvaluationObservation],
    *,
    horizon_days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Cohort retention in a [horizon-1, horizon+1) day window."""

    rows = list(observations)
    now = now or datetime.now(UTC)
    by_student: dict[UUID, list[datetime]] = defaultdict(list)
    for row in rows:
        by_student[row.student_id].append(row.occurred_at)
    eligible = []
    for student_id, timestamps in by_student.items():
        first = min(timestamps)
        if first + timedelta(days=horizon_days + 1) > now:
            continue
        retained = any(
            first + timedelta(days=horizon_days - 1)
            <= ts
            < first + timedelta(days=horizon_days + 1)
            for ts in timestamps
        )
        eligible.append(retained)
    return _interval(sum(eligible), len(eligible))


def transfer_metric(
    observations: Iterable[EvaluationObservation],
) -> dict[str, Any]:
    rows = [
        row
        for row in observations
        if row.source == InteractionSource.transfer_probe.value
    ]
    return _interval(sum(row.is_correct for row in rows), len(rows))


def no_ai_transfer_metric(
    observations: Iterable[EvaluationObservation],
) -> dict[str, Any]:
    """Measure explicitly tagged independent transfer probes.

    Historical transfer rows without explicit flags remain useful to
    ``transfer_metric`` but are not silently advertised as a no-AI result.
    """

    rows = [
        row
        for row in observations
        if row.source == InteractionSource.transfer_probe.value
        and row.independent_mode is True
        and row.ai_assisted is False
    ]
    result: dict[str, Any] = _interval(sum(row.is_correct for row in rows), len(rows))
    result["note"] = (
        "仅统计 independent_mode=true 且 ai_assisted=false 的迁移探针；"
        "未显式标注的历史事件不作 no-AI 结论"
    )
    return result


def delayed_gain_metric(
    observations: Iterable[EvaluationObservation],
) -> dict[str, Any]:
    """Compute paired delayed-minus-baseline correctness gain.

    ``evaluation_phase`` is explicit event metadata with values ``baseline``
    or ``delayed``. Missing pairs return null rather than mixing cohorts.
    """

    by_student: dict[UUID, dict[str, list[float]]] = defaultdict(
        lambda: {"baseline": [], "delayed": []}
    )
    for row in observations:
        if row.evaluation_phase in {"baseline", "delayed"}:
            by_student[row.student_id][row.evaluation_phase].append(
                float(row.is_correct)
            )

    gains: list[float] = []
    for phases in by_student.values():
        if phases["baseline"] and phases["delayed"]:
            gains.append(mean(phases["delayed"]) - mean(phases["baseline"]))
    if not gains:
        return {
            "value": None,
            "paired_n": 0,
            "positive_gain_rate": None,
            "note": "需要同一学生同时有 baseline 与 delayed 观测",
        }
    return {
        "value": round(mean(gains), 6),
        "paired_n": len(gains),
        "positive_gain_rate": round(sum(g > 0 for g in gains) / len(gains), 6),
        "note": "paired delayed-minus-baseline correctness；不是无随机化的因果结论",
    }


def time_split_counts(
    observations: Iterable[EvaluationObservation],
    *,
    train_end: datetime,
    eval_start: datetime,
    eval_end: datetime,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Assign observations to non-overlapping train/eval windows."""

    for boundary in (train_end, eval_start, eval_end, as_of):
        if boundary is not None and (
            boundary.tzinfo is None or boundary.utcoffset() is None
        ):
            raise ValueError("evaluation time boundaries must be timezone-aware")
    if eval_start < train_end or eval_end <= eval_start:
        raise ValueError("evaluation windows must be ordered and non-overlapping")

    train = evaluation = future_excluded = outside = 0
    for row in observations:
        if as_of is not None and (
            row.occurred_at > as_of
            or (row.received_at is not None and row.received_at > as_of)
        ):
            future_excluded += 1
        elif row.occurred_at < train_end:
            train += 1
        elif eval_start <= row.occurred_at < eval_end:
            evaluation += 1
        else:
            outside += 1
    return {
        "train_n": train,
        "evaluation_n": evaluation,
        "future_excluded_n": future_excluded,
        "outside_n": outside,
        "train_end": train_end.isoformat(),
        "eval_start": eval_start.isoformat(),
        "eval_end": eval_end.isoformat(),
        "as_of": as_of.isoformat() if as_of is not None else None,
        "overlap": False,
    }


def uplift_metric(
    observations: Iterable[EvaluationObservation],
    *,
    treatment_arm: str = "worked_example",
    control_arm: str = "control",
) -> dict[str, Any]:
    """Observed arm difference; no value is emitted for a missing arm."""

    groups: dict[str, list[EvaluationObservation]] = defaultdict(list)
    for row in observations:
        if row.treatment in {treatment_arm, control_arm}:
            groups[row.treatment].append(row)
    treatment = groups.get(treatment_arm, [])
    control = groups.get(control_arm, [])
    if not treatment or not control:
        return {
            "value": None,
            "treatment_n": len(treatment),
            "control_n": len(control),
            "note": "两臂均有观测后才计算 uplift；当前不是因果结论",
        }
    t_mean = mean(float(row.is_correct) for row in treatment)
    c_mean = mean(float(row.is_correct) for row in control)
    t_minutes = sum((row.time_spent_seconds or 0.0) for row in treatment) / 60.0
    c_minutes = sum((row.time_spent_seconds or 0.0) for row in control) / 60.0
    return {
        "value": round(t_mean - c_mean, 6),
        "treatment_mean": round(t_mean, 6),
        "control_mean": round(c_mean, 6),
        "treatment_n": len(treatment),
        "control_n": len(control),
        "treatment_minutes": round(t_minutes, 4),
        "control_minutes": round(c_minutes, 4),
        "note": "观察性 arm difference；需预注册/随机化与延迟终点后才可作因果解释",
    }


def evaluation_report(
    observations: Iterable[EvaluationObservation],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    rows = list(observations)
    return {
        "evaluation_version": "evaluation-os/v2",
        "computed_at": (now or datetime.now(UTC)).isoformat(),
        "n_events": len(rows),
        "n_students": len({row.student_id for row in rows}),
        "retention": {
            "d7": retention_at_horizon(rows, horizon_days=7, now=now),
            "d30": retention_at_horizon(rows, horizon_days=30, now=now),
        },
        "transfer": transfer_metric(rows),
        "no_ai_transfer": no_ai_transfer_metric(rows),
        "delayed_gain": delayed_gain_metric(rows),
        "uplift": uplift_metric(rows),
        "guardrails": {
            "no_student_ids_in_output": True,
            "time_split": "cohort anchor before outcome window; future events excluded by now",
            "insufficient_samples_return_null": True,
            "no_ai_requires_explicit_flags": True,
            "delayed_gain_requires_paired_phases": True,
        },
    }


async def evaluation_os_report(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(
                InteractionEvent.student_id,
                InteractionEvent.occurred_at,
                InteractionEvent.is_correct,
                InteractionEvent.source,
                InteractionEvent.time_spent_seconds,
                InteractionEvent.tutor_mode,
                InteractionEvent.ai_assisted,
                InteractionEvent.independent_mode,
                InteractionEvent.evaluation_phase,
                InteractionEvent.received_at,
            ).where(InteractionEvent.student_id.is_not(None))
        )
    ).all()
    observations = [
        EvaluationObservation(
            student_id=student_id,
            occurred_at=occurred_at,
            is_correct=bool(is_correct),
            source=getattr(source, "value", str(source)),
            treatment=student_arm(student_id),
            time_spent_seconds=(
                float(time_spent_seconds) if time_spent_seconds is not None else None
            ),
            tutor_mode=tutor_mode,
            ai_assisted=ai_assisted,
            independent_mode=independent_mode,
            evaluation_phase=evaluation_phase,
            received_at=received_at,
        )
        for (
            student_id,
            occurred_at,
            is_correct,
            source,
            time_spent_seconds,
            tutor_mode,
            ai_assisted,
            independent_mode,
            evaluation_phase,
            received_at,
        ) in rows
    ]
    return evaluation_report(observations, now=now)
