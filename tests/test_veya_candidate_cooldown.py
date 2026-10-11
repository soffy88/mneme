"""VeyaTextCaller：慢候选短超时 + 冷却跳过（2026-10-11）。"""

import asyncio
from typing import Any

import httpx

from services.providers import veya_caller
from services.providers.veya_caller import VeyaTextCaller

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _run(monkeypatch: Any, handler: Any) -> tuple[dict[str, Any], list[str]]:
    seen: list[str] = []

    def _h(request: httpx.Request) -> httpx.Response:
        import json

        model = json.loads(request.content)["model"]
        seen.append(model)
        return handler(model)

    transport = httpx.MockTransport(_h)
    def _client(*a: Any, **k: Any) -> httpx.AsyncClient:
        k["transport"] = transport
        return _REAL_ASYNC_CLIENT(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", _client)
    monkeypatch.setenv("VEYA_BASE_URL", "http://veya.test/v1")
    caller = VeyaTextCaller("slow-free,good-model")
    out = asyncio.run(caller(messages=[{"role": "user", "content": "hi"}], max_tokens=50))
    return out, seen


def _ok(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}]})


def test_timeout_falls_through_and_cools_down(monkeypatch: Any) -> None:
    veya_caller._CANDIDATE_COOLDOWN_UNTIL.clear()

    def handler(model: str) -> httpx.Response:
        if model == "slow-free":
            raise httpx.ReadTimeout("slow")
        return _ok("hello")

    out, seen = _run(monkeypatch, handler)
    assert out["content"] == "hello" and seen == ["slow-free", "good-model"]
    out2, seen2 = _run(monkeypatch, handler)
    assert out2["content"] == "hello" and seen2 == ["good-model"]
    veya_caller._CANDIDATE_COOLDOWN_UNTIL.clear()


def test_all_cooling_still_tries_everyone(monkeypatch: Any) -> None:
    veya_caller._CANDIDATE_COOLDOWN_UNTIL.clear()
    veya_caller._CANDIDATE_COOLDOWN_UNTIL.update({"slow-free": 1e18, "good-model": 1e18})
    out, seen = _run(monkeypatch, lambda m: _ok("ok"))
    assert out["content"] == "ok" and seen == ["slow-free"]
    assert "slow-free" not in veya_caller._CANDIDATE_COOLDOWN_UNTIL
    veya_caller._CANDIDATE_COOLDOWN_UNTIL.clear()
