"""Evaluation ModelRegistry service.

The registry is metadata-only: it stores model identity, train/eval windows,
metrics and lifecycle status, never student events or learner state.  Window
validation is pure and deliberately fail-closed so a model cannot be promoted
from an evaluation that overlaps its training data or lies in the future.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import ModelRegistry

MODEL_STATUSES = frozenset({"shadow", "candidate", "production", "retired"})
STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "shadow": frozenset({"candidate", "retired"}),
    "candidate": frozenset({"shadow", "production", "retired"}),
    "production": frozenset({"retired"}),
    "retired": frozenset(),
}
MIN_PROMOTION_EVENTS = 30
_SHADOW_GUARDRAILS = (
    "writes_database",
    "controls_learning_path",
    "future_events_used",
    "causal_effect_claim",
)


class ModelRegistryError(ValueError):
    """Invalid registry metadata or lifecycle transition."""


def _require_aware(label: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ModelRegistryError(f"{label} must be timezone-aware")


def validate_model_window(
    *,
    model_id: str,
    model_type: str,
    code_sha: str,
    train_start: datetime,
    train_end: datetime,
    eval_start: datetime,
    eval_end: datetime,
    status: str = "shadow",
    rollback_to: str | None = None,
    as_of: datetime | None = None,
) -> None:
    """Validate a registry row without touching the database."""

    for label, value in (
        ("train_start", train_start),
        ("train_end", train_end),
        ("eval_start", eval_start),
        ("eval_end", eval_end),
    ):
        _require_aware(label, value)
    if as_of is not None:
        _require_aware("as_of", as_of)
    if not model_id.strip() or len(model_id) > 120:
        raise ModelRegistryError("model_id must be 1..120 characters")
    if not model_type.strip() or len(model_type) > 80:
        raise ModelRegistryError("model_type must be 1..80 characters")
    if not code_sha.strip() or len(code_sha) > 128:
        raise ModelRegistryError("code_sha must be 1..128 characters")
    if status not in MODEL_STATUSES:
        raise ModelRegistryError(f"unknown model status: {status}")
    if train_start >= train_end:
        raise ModelRegistryError("train window must have positive duration")
    if train_end > eval_start or eval_start >= eval_end:
        raise ModelRegistryError("train/eval windows must be ordered and non-overlapping")
    if as_of is not None and eval_end > as_of:
        raise ModelRegistryError("evaluation window extends beyond as_of")
    if rollback_to == model_id:
        raise ModelRegistryError("rollback_to cannot point to the same model")


def validate_status_transition(current: str, target: str) -> None:
    if target not in MODEL_STATUSES:
        raise ModelRegistryError(f"unknown model status: {target}")
    if target == current:
        return
    if target not in STATUS_TRANSITIONS.get(current, frozenset()):
        raise ModelRegistryError(f"invalid model transition: {current} -> {target}")


def validate_promotion_evidence(
    metrics: Mapping[str, Any], *, model_id: str | None = None
) -> None:
    """Require a complete, non-causal shadow report before promotion.

    The registry stores the complete report, not a hand-copied AUC.  This
    prevents an admin from promoting a model with an unscoped metric, a future
    evaluation, or a report that omitted the baseline comparison.  The gate is
    evidence-completeness only; it does not turn observed difference into a
    causal or product-effect claim.
    """

    if metrics.get("evaluation_version") != "shadow-evaluation/v1":
        raise ModelRegistryError(
            "promotion requires a shadow-evaluation/v1 report"
        )
    if metrics.get("mode") != "shadow_only":
        raise ModelRegistryError("promotion evidence must be shadow_only")
    if model_id is not None and metrics.get("model_id") != model_id:
        raise ModelRegistryError("promotion evidence model_id does not match registry")
    guardrails = metrics.get("guardrails")
    if not isinstance(guardrails, Mapping) or any(
        guardrails.get(name) is not False for name in _SHADOW_GUARDRAILS
    ):
        raise ModelRegistryError("promotion evidence has unsafe shadow guardrails")

    candidate = metrics.get("candidate")
    if not isinstance(candidate, Mapping):
        raise ModelRegistryError("promotion evidence is missing candidate metrics")
    sample_size = candidate.get("n")
    if (
        isinstance(sample_size, bool)
        or not isinstance(sample_size, int)
        or sample_size < MIN_PROMOTION_EVENTS
    ):
        raise ModelRegistryError(
            f"promotion requires at least {MIN_PROMOTION_EVENTS} shadow events"
        )
    for name in ("auc", "logloss", "brier", "ece", "calibration_slope"):
        value = candidate.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise ModelRegistryError(
                f"promotion evidence candidate.{name} must be finite"
            )
    baseline = metrics.get("baseline")
    if not isinstance(baseline, Mapping) or baseline.get("n") != sample_size:
        raise ModelRegistryError(
            "promotion evidence must contain an aligned baseline"
        )
    comparison = metrics.get("comparison")
    if not isinstance(comparison, Mapping) or not isinstance(
        comparison.get("candidate_vs_baseline"), Mapping
    ):
        raise ModelRegistryError(
            "promotion evidence must contain candidate_vs_baseline"
        )


def validate_status_evidence(
    target_status: str,
    metrics: Mapping[str, Any] | None,
    *,
    model_id: str | None = None,
) -> None:
    """Apply the evidence gate to candidate and production lifecycle states."""

    if target_status in {"candidate", "production"}:
        validate_promotion_evidence(metrics or {}, model_id=model_id)


def model_registry_payload(row: ModelRegistry) -> dict[str, Any]:
    """Serialize metadata without exposing any student-scoped information."""

    return {
        "model_id": row.model_id,
        "model_type": row.model_type,
        "code_sha": row.code_sha,
        "train_start": row.train_start.isoformat(),
        "train_end": row.train_end.isoformat(),
        "eval_start": row.eval_start.isoformat(),
        "eval_end": row.eval_end.isoformat(),
        "params": row.params or {},
        "metrics": row.metrics or {},
        "status": row.status,
        "rollback_to": row.rollback_to,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def register_model(
    db: AsyncSession,
    *,
    model_id: str,
    model_type: str,
    code_sha: str,
    train_start: datetime,
    train_end: datetime,
    eval_start: datetime,
    eval_end: datetime,
    params: Mapping[str, Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    status: str = "shadow",
    rollback_to: str | None = None,
    as_of: datetime | None = None,
) -> ModelRegistry:
    validate_model_window(
        model_id=model_id,
        model_type=model_type,
        code_sha=code_sha,
        train_start=train_start,
        train_end=train_end,
        eval_start=eval_start,
        eval_end=eval_end,
        status=status,
        rollback_to=rollback_to,
        as_of=as_of or datetime.now(UTC),
    )
    validate_status_evidence(status, metrics, model_id=model_id)
    existing = (
        await db.execute(
            select(ModelRegistry).where(ModelRegistry.model_id == model_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ModelRegistryError(f"model_id already exists: {model_id}")
    if rollback_to is not None:
        target = (
            await db.execute(
                select(ModelRegistry.model_id).where(
                    ModelRegistry.model_id == rollback_to
                )
            )
        ).scalar_one_or_none()
        if target is None:
            raise ModelRegistryError(f"rollback target not found: {rollback_to}")

    row = ModelRegistry(
        model_id=model_id,
        model_type=model_type,
        code_sha=code_sha,
        train_start=train_start,
        train_end=train_end,
        eval_start=eval_start,
        eval_end=eval_end,
        params=dict(params or {}),
        metrics=dict(metrics or {}),
        status=status,
        rollback_to=rollback_to,
    )
    db.add(row)
    await db.flush()
    return row


async def list_models(
    db: AsyncSession,
    *,
    model_type: str | None = None,
    status: str | None = None,
) -> list[ModelRegistry]:
    stmt = select(ModelRegistry).order_by(
        ModelRegistry.updated_at.desc(), ModelRegistry.model_id
    )
    if model_type is not None:
        stmt = stmt.where(ModelRegistry.model_type == model_type)
    if status is not None:
        if status not in MODEL_STATUSES:
            raise ModelRegistryError(f"unknown model status: {status}")
        stmt = stmt.where(ModelRegistry.status == status)
    return list((await db.execute(stmt)).scalars().all())


async def transition_model(
    db: AsyncSession,
    *,
    model_id: str,
    target_status: str,
    rollback_to: str | None = None,
    metrics: Mapping[str, Any] | None = None,
) -> ModelRegistry:
    row = (
        await db.execute(
            select(ModelRegistry).where(ModelRegistry.model_id == model_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise ModelRegistryError(f"model_id not found: {model_id}")
    validate_status_transition(row.status, target_status)
    effective_metrics = metrics if metrics is not None else row.metrics or {}
    validate_status_evidence(
        target_status,
        effective_metrics,
        model_id=model_id,
    )
    if rollback_to == model_id:
        raise ModelRegistryError("rollback_to cannot point to the same model")
    if rollback_to is not None:
        target = (
            await db.execute(
                select(ModelRegistry.model_id).where(
                    ModelRegistry.model_id == rollback_to
                )
            )
        ).scalar_one_or_none()
        if target is None:
            raise ModelRegistryError(f"rollback target not found: {rollback_to}")
    if target_status == "production":
        active = (
            await db.execute(
                select(ModelRegistry.model_id).where(
                    ModelRegistry.model_type == row.model_type,
                    ModelRegistry.status == "production",
                    ModelRegistry.model_id != model_id,
                )
            )
        ).scalar_one_or_none()
        if active is not None:
            raise ModelRegistryError(
                f"another production model exists for {row.model_type}: {active}"
            )
    row.status = target_status
    if metrics is not None:
        row.metrics = dict(metrics)
    if rollback_to is not None:
        row.rollback_to = rollback_to
    row.updated_at = datetime.now(UTC)
    await db.flush()
    return row
