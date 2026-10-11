"""推理模型回退可靠性（2026-10-11 生产事故回归）。

Veya 宕机 → 回退链落到 InternAI Agents-A1（推理模型）：
  - 小 max_tokens 下思考吃光额度，content 为空、finish_reason=length；
  - ``enable_thinking=False`` 被端点忽略，``thinking={"type":"disabled"}`` 才有效；
  - 长生成常 >60s，被 65s 的包装层超时砍掉并计入熔断；
  - 活书 7 章并发调用一起超时把熔断器打开。

钉住：thinking.disabled + max_tokens 下限、空 content 算失败并换下一个候选/端点、
推理链用长超时档（且仍有 300s 硬上限）、活书 LLM 调用跨进程并发上限。
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from obase.provider_registry import ProviderRegistry
from obase.provider_timeout import ProviderTimeoutPolicy
from services.providers import setup as provider_setup
from services.providers.internai_caller import FallbackTextCaller, InternAiTextCaller
from services.providers.reliability import ProviderReliabilityConfig, ReliableProvider
from services.providers.veya_caller import (
    EmptyCompletionError,
    VeyaTextCaller,
    is_reasoning_model,
)


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


def _stub_httpx(monkeypatch, handler, seen_timeouts=None):
    class _C:
        def __init__(self, **kw):
            if seen_timeouts is not None:
                seen_timeouts.append(kw.get("timeout"))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            return handler(url, headers, json)

    monkeypatch.setitem(
        sys.modules,
        "httpx",
        type("m", (), {"AsyncClient": _C, "Timeout": lambda **kw: dict(kw)}),
    )


def _ok(content, finish="stop"):
    return _Resp(
        {"choices": [{"message": {"content": content}, "finish_reason": finish}], "usage": {}}
    )


def test_reasoning_model_list_is_env_driven(monkeypatch):
    monkeypatch.delenv("MNEME_REASONING_MODELS", raising=False)
    assert is_reasoning_model("Agents-A1")
    assert is_reasoning_model("agents-a1")
    assert not is_reasoning_model("veya1.2")
    monkeypatch.setenv("MNEME_REASONING_MODELS", "r1, other")
    assert is_reasoning_model("R1") and not is_reasoning_model("Agents-A1")


def test_reasoning_candidate_gets_thinking_off_and_token_floor(monkeypatch):
    monkeypatch.setenv("INTERN_AI_API_KEY", "k")
    for k in ("MNEME_REASONING_MODELS", "MNEME_REASONING_MIN_TOKENS",
              "MNEME_REASONING_THINKING_OFF", "INTERN_AI_MODEL"):
        monkeypatch.delenv(k, raising=False)
    payloads: list[dict] = []
    timeouts: list = []

    def handler(url, headers, payload):
        payloads.append(payload)
        return _ok("答案")

    _stub_httpx(monkeypatch, handler, timeouts)
    out = asyncio.run(InternAiTextCaller()(messages=[{"role": "user", "content": "x"}],
                                           max_tokens=600))
    assert out["content"] == "答案"
    assert payloads[0]["thinking"] == {"type": "disabled"}
    assert payloads[0]["max_tokens"] >= 8192
    # 推理端点的 HTTP 读超时长于共享策略（60s 默认）
    assert timeouts[0]["read"] >= 150


def test_explicit_enable_thinking_true_is_respected(monkeypatch):
    monkeypatch.setenv("INTERN_AI_API_KEY", "k")
    monkeypatch.delenv("INTERN_AI_MODEL", raising=False)
    payloads: list[dict] = []
    _stub_httpx(monkeypatch, lambda u, h, p: (payloads.append(p), _ok("ok"))[1])
    asyncio.run(InternAiTextCaller()(messages=[], max_tokens=600, enable_thinking=True))
    assert "thinking" not in payloads[0]


def test_non_reasoning_candidate_is_untouched(monkeypatch):
    monkeypatch.delenv("MNEME_REASONING_MODELS", raising=False)
    payloads: list[dict] = []
    timeouts: list = []
    _stub_httpx(monkeypatch, lambda u, h, p: (payloads.append(p), _ok("ok"))[1], timeouts)
    asyncio.run(VeyaTextCaller(model="veya1.2")(messages=[], max_tokens=600))
    assert payloads[0]["max_tokens"] == 600
    assert "thinking" not in payloads[0]


def test_empty_content_falls_through_to_next_candidate(monkeypatch):
    seen: list[str] = []

    def handler(url, headers, payload):
        seen.append(payload["model"])
        if payload["model"] == "m1":
            return _ok("", finish="length")
        return _ok("from-m2")

    _stub_httpx(monkeypatch, handler)
    c = VeyaTextCaller(model="m1,m2")
    out = asyncio.run(c(messages=[], max_tokens=100))
    assert seen == ["m1", "m2"]
    assert out["content"] == "from-m2"
    assert c.last_good_model == "m2"


def test_all_empty_raises_typed_error(monkeypatch):
    _stub_httpx(monkeypatch, lambda u, h, p: _ok("   ", finish="length"))
    with pytest.raises(EmptyCompletionError) as ei:
        asyncio.run(VeyaTextCaller(model="m1,m2")(messages=[], max_tokens=100))
    assert "empty_content(finish=length)" in str(ei.value)


def test_tool_calls_with_empty_content_is_not_empty(monkeypatch):
    _stub_httpx(
        monkeypatch,
        lambda u, h, p: _Resp({"choices": [{"message": {"content": None,
                                                         "tool_calls": [{"id": "t"}]},
                                            "finish_reason": "tool_calls"}]}),
    )
    out = asyncio.run(VeyaTextCaller(model="m1")(messages=[], max_tokens=100))
    assert out["content"] == ""


class _Stub:
    def __init__(self, content, reasoning=False):
        self.content = content
        self.models = ["s"]
        self.model = "s"
        self.last_good_model = None
        self.has_reasoning_model = reasoning
        self.calls = 0

    async def __call__(self, **_kw):
        self.calls += 1
        return {"content": self.content, "usage": {}}


def test_fallback_chain_treats_empty_content_as_failure():
    a, b = _Stub(""), _Stub("from-b")
    out = asyncio.run(FallbackTextCaller([a, b])(messages=[]))
    assert out["content"] == "from-b"
    assert a.calls == 1 and b.calls == 1


def test_fallback_chain_all_empty_raises():
    with pytest.raises(RuntimeError, match="empty_content"):
        asyncio.run(FallbackTextCaller([_Stub(""), _Stub(" ")])(messages=[]))


def test_chain_reports_reasoning_membership():
    assert FallbackTextCaller([_Stub("x"), _Stub("y", reasoning=True)]).has_reasoning_model
    assert not FallbackTextCaller([_Stub("x")]).has_reasoning_model


def test_reasoning_profile_is_longer_but_still_hard_bounded(monkeypatch):
    for k in ("MNEME_REASONING_READ_TIMEOUT_SECONDS", "MNEME_REASONING_TOTAL_TIMEOUT_SECONDS"):
        monkeypatch.delenv(k, raising=False)
    base = ProviderReliabilityConfig.from_env()
    prof = base.for_reasoning()
    assert prof.long_running
    assert prof.timeout.read_seconds == 150
    assert prof.total_timeout_seconds > base.total_timeout_seconds
    assert prof.max_retries <= 1
    # 熔断/预算不放宽
    assert prof.circuit_failure_threshold == base.circuit_failure_threshold
    assert prof.cost_usd_per_window == base.cost_usd_per_window
    monkeypatch.setenv("MNEME_REASONING_READ_TIMEOUT_SECONDS", "9999")
    assert ProviderReliabilityConfig.from_env().for_reasoning().timeout.read_seconds == 300
    # 通用档仍是 120s 上限；长档 300s 上限
    with pytest.raises(ValueError):
        ProviderReliabilityConfig(
            timeout=ProviderTimeoutPolicy(connect_seconds=5, read_seconds=150)
        )
    with pytest.raises(ValueError):
        ProviderReliabilityConfig(
            timeout=ProviderTimeoutPolicy(connect_seconds=5, read_seconds=301),
            long_running=True,
        )


def test_wrapper_for_reasoning_chain_uses_long_profile():
    reg = ProviderRegistry.get()
    saved = dict(reg._llms)
    try:
        reg._llms.clear()
        reg._llms["default"] = FallbackTextCaller([_Stub("x", reasoning=True)])
        reg._llms["plain"] = _Stub("y")
        provider_setup._install_reliability_wrappers("veya")
        assert isinstance(reg._llms["default"], ReliableProvider)
        assert reg._llms["default"].config.long_running
        assert not reg._llms["plain"].config.long_running
    finally:
        reg._llms.clear()
        reg._llms.update(saved)


async def test_book_compile_llm_slots_cap_concurrency(monkeypatch, tmp_path):
    from services import book_compile_service as svc

    monkeypatch.setenv("MNEME_BOOK_COMPILE_SLOT_DIR", str(tmp_path))
    monkeypatch.setenv("MNEME_BOOK_COMPILE_LLM_CONCURRENCY", "3")
    live = 0
    peak = 0

    async def fake_raw(**_kw):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.15)
        live -= 1
        return {"content": "ok", "usage": {}}

    budget = svc.BudgetCaller(fake_raw, cap_usd=10.0, model="claude-sonnet-4-5")
    await asyncio.gather(*(budget(messages=[{"role": "user", "content": "x"}])
                           for _ in range(7)))
    assert peak == 3
    assert budget.ok_calls == 7
