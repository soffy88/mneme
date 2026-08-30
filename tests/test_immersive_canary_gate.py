"""Fail-closed, server-side per-user Immersive canary gate contract."""

from __future__ import annotations

import uuid

import pytest

from services.feature_flags import (
    immersive_gate_reason,
    immersive_learning_canary_user_ids,
    is_immersive_learning_enabled_for_user,
)
from services.production_config import (
    ProductionConfigError,
    validate_environment_name,
    validate_production_deploy_preflight,
)


A = uuid.UUID("11111111-1111-4111-8111-111111111111")
B = uuid.UUID("22222222-2222-4222-8222-222222222222")


@pytest.mark.parametrize("value", ["", "unknown", "prod-like"])
def test_invalid_environment_is_rejected(value: str) -> None:
    with pytest.raises(ProductionConfigError):
        validate_environment_name(value, require_explicit=True)


def test_production_preflight_requires_explicit_identity() -> None:
    with pytest.raises(ProductionConfigError):
        validate_production_deploy_preflight({"MNEME_ENV": "demo"})
    with pytest.raises(ProductionConfigError):
        validate_production_deploy_preflight({"MNEME_ENV": "production"})


def test_canary_gate_global_off_allowlist_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMERSIVE_LEARNING_ENABLED", "false")
    monkeypatch.delenv("IMMERSIVE_LEARNING_CANARY_USER_IDS", raising=False)
    assert immersive_learning_canary_user_ids() == frozenset()
    assert not is_immersive_learning_enabled_for_user(A)
    assert immersive_gate_reason(A) == "DISABLED"


def test_canary_gate_exact_users_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMERSIVE_LEARNING_ENABLED", "0")
    monkeypatch.setenv("IMMERSIVE_LEARNING_CANARY_USER_IDS", f"  {A} , {A} ")
    assert immersive_learning_canary_user_ids() == {str(A)}
    assert is_immersive_learning_enabled_for_user(A)
    assert immersive_gate_reason(A) == "CANARY"
    assert not is_immersive_learning_enabled_for_user(B)


@pytest.mark.parametrize("raw", ["*", "all", f"{A},not-a-uuid", f"{A}, {B}, *"])
def test_malformed_or_wildcard_allowlist_fails_closed(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("IMMERSIVE_LEARNING_ENABLED", "0")
    monkeypatch.setenv("IMMERSIVE_LEARNING_CANARY_USER_IDS", raw)
    assert immersive_learning_canary_user_ids() == frozenset()
    assert not is_immersive_learning_enabled_for_user(A)


def test_global_on_allows_users_without_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMMERSIVE_LEARNING_ENABLED", "true")
    monkeypatch.delenv("IMMERSIVE_LEARNING_CANARY_USER_IDS", raising=False)
    assert is_immersive_learning_enabled_for_user(A)
    assert is_immersive_learning_enabled_for_user(B)
    assert immersive_gate_reason(A) == "GLOBAL"
