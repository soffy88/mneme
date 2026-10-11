"""MNEME_LLM_VEYA_FIRST 决定 Veya 在 FallbackTextCaller 链中的位置（2026-10-11）。"""

from typing import Any

from services.providers import internai_caller, setup
from services.providers.internai_caller import InternAiTextCaller
from services.providers.veya_caller import VeyaTextCaller


def _chain(monkeypatch: Any, veya_first: str | None) -> list[Any]:
    captured: list[list[Any]] = []

    class _Spy(internai_caller.FallbackTextCaller):  # type: ignore[misc]
        def __init__(self, callers: list[Any]) -> None:
            captured.append(list(callers))
            super().__init__(callers)

    monkeypatch.setattr(internai_caller, "FallbackTextCaller", _Spy)
    monkeypatch.setenv("MNEME_LLM", "veya")
    monkeypatch.setenv("INTERN_AI_API_KEY", "test-key")
    monkeypatch.setenv("VEYA_MODEL", "veya-free")
    if veya_first is None:
        monkeypatch.delenv("MNEME_LLM_VEYA_FIRST", raising=False)
    else:
        monkeypatch.setenv("MNEME_LLM_VEYA_FIRST", veya_first)
    monkeypatch.setattr(setup, "_CONFIGURATION_SIGNATURE", None, raising=False)
    setup.configure_llm_providers()
    assert captured, "FallbackTextCaller was not built"
    return captured[-1]


def test_default_order_internai_first(monkeypatch: Any) -> None:
    chain = _chain(monkeypatch, None)
    assert isinstance(chain[0], InternAiTextCaller)
    assert isinstance(chain[-1], VeyaTextCaller)


def test_veya_first_flag(monkeypatch: Any) -> None:
    chain = _chain(monkeypatch, "1")
    assert isinstance(chain[0], VeyaTextCaller)
    assert isinstance(chain[-1], InternAiTextCaller)
