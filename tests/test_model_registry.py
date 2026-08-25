"""Blueprint P5 ModelRegistry metadata and lifecycle contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.model_registry import (
    ModelRegistryError,
    validate_promotion_evidence,
    validate_model_window,
    validate_status_transition,
)


BASE = datetime(2026, 7, 1, tzinfo=UTC)


def _valid(**overrides):
    values = {
        "model_id": "bkt-shadow-2026-07",
        "model_type": "knowledge_tracing",
        "code_sha": "a" * 40,
        "train_start": BASE,
        "train_end": BASE + timedelta(days=20),
        "eval_start": BASE + timedelta(days=20),
        "eval_end": BASE + timedelta(days=30),
        "as_of": BASE + timedelta(days=31),
    }
    values.update(overrides)
    return values


def test_registry_requires_non_overlapping_historical_windows():
    validate_model_window(**_valid())

    with pytest.raises(ModelRegistryError, match="ordered and non-overlapping"):
        validate_model_window(
            **_valid(eval_start=BASE + timedelta(days=19))
        )
    with pytest.raises(ModelRegistryError, match="beyond as_of"):
        validate_model_window(
            **_valid(as_of=BASE + timedelta(days=25))
        )


def test_registry_rejects_naive_boundaries_and_self_rollback():
    with pytest.raises(ModelRegistryError, match="timezone-aware"):
        validate_model_window(
            **_valid(train_start=datetime(2026, 7, 1))
        )
    with pytest.raises(ModelRegistryError, match="same model"):
        validate_model_window(**_valid(rollback_to="bkt-shadow-2026-07"))


def test_model_lifecycle_is_explicit_and_production_does_not_auto_replace():
    validate_status_transition("shadow", "candidate")
    validate_status_transition("candidate", "production")
    validate_status_transition("production", "retired")

    with pytest.raises(ModelRegistryError, match="invalid model transition"):
        validate_status_transition("production", "shadow")
    with pytest.raises(ModelRegistryError, match="invalid model transition"):
        validate_status_transition("retired", "production")


def _shadow_evidence(model_id: str = "bkt-shadow-2026-07", n: int = 30) -> dict:
    return {
        "evaluation_version": "shadow-evaluation/v1",
        "model_id": model_id,
        "mode": "shadow_only",
        "candidate": {
            "n": n,
            "auc": 0.7,
            "logloss": 0.6,
            "brier": 0.2,
            "ece": 0.1,
            "calibration_slope": 0.9,
        },
        "baseline": {"model_id": "kernel-v1", "n": n},
        "comparison": {"candidate_vs_baseline": {"auc_delta": 0.02}},
        "guardrails": {
            "writes_database": False,
            "controls_learning_path": False,
            "future_events_used": False,
            "causal_effect_claim": False,
        },
    }


def test_promotion_evidence_requires_complete_aligned_shadow_report():
    validate_promotion_evidence(_shadow_evidence())

    with pytest.raises(ModelRegistryError, match="at least 30"):
        validate_promotion_evidence(_shadow_evidence(n=29))
    with pytest.raises(ModelRegistryError, match="aligned baseline"):
        validate_promotion_evidence(
            {**_shadow_evidence(), "baseline": {"model_id": "kernel-v1", "n": 29}}
        )
    with pytest.raises(ModelRegistryError, match="unsafe shadow guardrails"):
        validate_promotion_evidence(
            {
                **_shadow_evidence(),
                "guardrails": {
                    **_shadow_evidence()["guardrails"],
                    "causal_effect_claim": True,
                },
            }
        )
    with pytest.raises(ModelRegistryError, match="does not match"):
        validate_promotion_evidence(_shadow_evidence(), model_id="other-model")
    with pytest.raises(ModelRegistryError, match="candidate.auc must be finite"):
        evidence = _shadow_evidence()
        evidence["candidate"]["auc"] = float("nan")
        validate_promotion_evidence(evidence)
