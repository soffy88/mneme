"""Discovery API（独立端点）caller + 跨端点回退链的回归测试。

为什么要有第二个端点（2026-10-04）：Veya 侧 28 个上游只剩 2 个可用，而此前的
冗余是「**同一端点换模型名**」—— 端点整条链坏掉时名单里每个模型一起失败。
跨**端点**回退才有意义。

另外钉住一个推理模型特有的坑：`Agents-A1` 把预算先花在思考上，实测在
`max_tokens=8192` 下 JSON 被**截断在半截字符串**（HTTP 200、正文 465 字符），
而 caller 原本不返回 `finish_reason`，于是截断被 `llm_complete` 默认成
`end_turn`，表现得像「prompt/模型格式错误」—— 真因是预算不足。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from services.providers.internai_caller import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    FallbackTextCaller,
    InternAiTextCaller,
)


class _Resp:
    def __init__(self, payload):
        self._p = payload
        self.status = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


def _stub_httpx(monkeypatch, handler):
    import sys

    class _C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            return handler(url, headers, json)

    monkeypatch.setitem(
        sys.modules,
        "httpx",
        type("m", (), {"AsyncClient": lambda **kw: _C(), "Timeout": lambda **kw: object()}),
    )


def test_defaults_are_discovery_api(monkeypatch):
    for k in ("INTERN_AI_BASE_URL", "INTERN_AI_MODEL", "INTERN_AI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    c = InternAiTextCaller()
    assert c.base_url == DEFAULT_BASE_URL
    assert c.models == [DEFAULT_MODEL]
    assert c.model == DEFAULT_MODEL


def test_reads_env_and_supports_model_list(monkeypatch):
    monkeypatch.setenv("INTERN_AI_BASE_URL", "https://example.invalid/v1/")
    monkeypatch.setenv("INTERN_AI_MODEL", "Agents-A1, backup-model")
    monkeypatch.setenv("INTERN_AI_API_KEY", "k")
    c = InternAiTextCaller()
    assert c.base_url == "https://example.invalid/v1"  # 尾部斜杠去掉
    assert c.models == ["Agents-A1", "backup-model"]
    assert c._auth_headers() == {"Authorization": "Bearer k"}


def test_passes_finish_reason_through(monkeypatch):
    """截断必须**可见** —— 否则会被误判成格式错误（真因是 max_tokens 不足）。"""
    monkeypatch.setenv("INTERN_AI_API_KEY", "k")
    c = InternAiTextCaller()

    def handler(url, headers, payload):
        return _Resp(
            {
                "choices": [
                    {"message": {"content": '[{"word":"x"'}, "finish_reason": "length"}
                ],
                "usage": {},
            }
        )

    _stub_httpx(monkeypatch, handler)
    out = asyncio.run(c(messages=[{"role": "user", "content": "hi"}], max_tokens=16))
    assert out["finish_reason"] == "length"
    # llm_complete 就是读这个键填 stop_reason
    assert out["finish_reason"] in json.dumps(out)


# ── 跨端点回退链 ──────────────────────────────────────────────────────────


class _StubCaller:
    def __init__(self, name, ok=False, exc=None, last_good=None):
        self.name = name
        self.models = [f"{name}-model"]
        self.model = f"{name}-model"
        self.last_good_model = last_good
        self._ok = ok
        self._exc = exc

    async def __call__(self, **_kw):
        if self._exc:
            raise self._exc
        if not self._ok:
            raise RuntimeError(f"{self.name} 挂了")
        return {"content": f"from-{self.name}", "usage": {}, "finish_reason": "stop"}


def test_falls_through_to_second_endpoint():
    chain = FallbackTextCaller(
        [_StubCaller("A", ok=False), _StubCaller("B", ok=True, last_good="B-model")]
    )
    out = asyncio.run(chain(messages=[]))
    assert out["content"] == "from-B"
    assert chain.last_good_model == "B-model"


def test_all_endpoints_failing_names_every_one():
    chain = FallbackTextCaller(
        [_StubCaller("A", exc=RuntimeError("boom-a")), _StubCaller("B", exc=RuntimeError("boom-b"))]
    )
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(chain(messages=[]))
    msg = str(ei.value)
    assert "all text endpoints failed" in msg
    assert "boom-a" in msg and "boom-b" in msg, "必须能看出是哪个端点挂的"


def test_chain_requires_at_least_one_caller():
    with pytest.raises(ValueError):
        FallbackTextCaller([])


def test_chain_exposes_flat_model_list_for_observability():
    """候选名单要跨端点摊平 —— `/health/providers` 靠它报 llm_model_candidates。"""
    chain = FallbackTextCaller([_StubCaller("A"), _StubCaller("B")])
    assert chain.models == ["A-model", "B-model"]
