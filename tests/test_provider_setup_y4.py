"""Y.4：MNEME_LLM=qwen 缺 key 时不得静默装 mock（除非显式允许）。"""

from __future__ import annotations


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


def test_production_rejects_default_mock_llm(monkeypatch):
    monkeypatch.setenv("MNEME_ENV", "production")
    monkeypatch.setenv("MNEME_LLM", "")
    for name in (
        "DEEPSEEK_API_KEY",
        "QWEN_API_KEY",
        "DASHSCOPE_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    # `obase.config.settings` is initialized at import time from the local
    # .env; make the no-credential fixture deterministic without inspecting or
    # printing any secret value.
    import obase.config as obase_config

    for name in (
        "DEEPSEEK_API_KEY",
        "QWEN_API_KEY",
        "DASHSCOPE_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.setattr(obase_config.settings, name, "your_key_here")
    import services.providers.setup as setup

    with pytest.raises(RuntimeError, match="production requires a live LLM provider"):
        setup.configure_llm_providers()


def test_veya_registers_local_text_and_vision(monkeypatch):
    monkeypatch.setenv("MNEME_LLM", "veya")
    monkeypatch.setenv("VEYA_BASE_URL", "http://veya.test/v1")
    monkeypatch.setenv("VEYA_MODEL", "veya1.2-128K")
    monkeypatch.setenv("VEYA_VL_MODEL", "veya1.2-vl")

    from services.providers.setup import configure_llm_providers

    assert configure_llm_providers() == "veya"
    registry = ProviderRegistry.get()
    llm = registry.llm()
    vlm = registry.vlm()
    assert type(llm).__name__ == "ReliableProvider"
    assert type(vlm).__name__ == "ReliableProvider"
    assert type(llm.caller).__name__ == "VeyaTextCaller"
    assert type(vlm.caller).__name__ == "VeyaVLCaller"
    assert llm.model == "veya1.2-128K"
    assert vlm.model == "veya1.2-vl"
    assert llm.base_url == "http://veya.test/v1"
    assert vlm.base_url == "http://veya.test/v1"


def test_agent_loop_uses_the_same_reliability_wrapper(monkeypatch):
    monkeypatch.setenv("MNEME_LLM", "veya")
    monkeypatch.setenv("VEYA_BASE_URL", "http://veya.test/v1")
    from services.providers.setup import get_agent_loop_caller
    from services.providers.reliability import ReliableProvider

    caller = get_agent_loop_caller()
    assert isinstance(caller, ReliableProvider)
    assert type(caller.caller).__name__ == "VeyaLoopCaller"
    assert caller.retryable is True
