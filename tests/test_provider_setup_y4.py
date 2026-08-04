"""Y.4：MNEME_LLM=qwen 缺 key 时不得静默装 mock（除非显式允许）。"""

from __future__ import annotations

import os

import pytest

from obase.provider_registry import ProviderRegistry


@pytest.fixture(autouse=True)
def _reset_registry():
    ProviderRegistry.reset()
    yield
    ProviderRegistry.reset()


def test_provider_status_shape(monkeypatch):
    monkeypatch.setenv("MNEME_ALLOW_MOCK_LLM", "1")
    monkeypatch.setenv("MNEME_LLM", "")
    from services.providers.setup import configure_llm_providers, provider_status

    configure_llm_providers()
    st = provider_status()
    assert "llm" in st and "vlm" in st
    assert "llm_is_mock" in st and "vlm_is_mock" in st


def test_qwen_missing_key_refuses_without_allow(monkeypatch):
    monkeypatch.setenv("MNEME_LLM", "qwen")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("MNEME_ALLOW_MOCK_LLM", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    # 清掉 pytest 标记后仍可能有 — 用 ALLOW=0 显式
    monkeypatch.setenv("MNEME_ALLOW_MOCK_LLM", "0")
    # 绕过 pytest 自动允许：直接测 _allow_mock 关掉时的 RuntimeError
    import services.providers.setup as setup

    monkeypatch.setattr(setup, "_allow_mock", lambda: False)
    with pytest.raises(RuntimeError, match="假批改"):
        setup.configure_llm_providers()


def test_qwen_missing_key_allowed_with_flag(monkeypatch):
    monkeypatch.setenv("MNEME_LLM", "qwen")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setenv("MNEME_ALLOW_MOCK_LLM", "1")
    from services.providers.setup import configure_llm_providers

    assert configure_llm_providers() == "qwen-missing-key-mock"
