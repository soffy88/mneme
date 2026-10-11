"""VeyaTextCaller：慢候选短超时 + 冷却跳过（2026-10-11）。"""

import asyncio
import json
from typing import Any

import httpx

from services.providers import veya_caller
from services.providers.veya_caller import VeyaTextCaller

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _install(monkeypatch: Any, handler: Any, seen: list[str]) -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        seen.append(model)
        return handler(model)

    transport = httpx.MockTransport(_h)

    def _client(*a: Any, **k: Any) -> httpx.AsyncClient:
        k["transport"] = transport
        return _REAL_ASYNC_CLIENT(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", _client)
    monkeypatch.setenv("VEYA_BASE_URL", "http://veya.test/v1")


def _ok(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}]}
    )


def _call(caller: VeyaTextCaller) -> dict[str, Any]:
    return asyncio.run(caller(messages=[{"role": "user", "content": "hi"}], max_tokens=50))


def test_timeout_falls_through_and_cools_down(monkeypatch: Any) -> None:
    seen: list[str] = []

    def handler(model: str) -> httpx.Response:
        if model == "slow-free":
            raise httpx.ReadTimeout("slow")
        return _ok("hello")

    _install(monkeypatch, handler, seen)
    caller = VeyaTextCaller("slow-free,good-model")
    assert _call(caller)["content"] == "hello"
    assert seen == ["slow-free", "good-model"]
    seen.clear()
    assert _call(caller)["content"] == "hello"
    assert seen == ["good-model"]


def test_all_cooling_still_tries_everyone(monkeypatch: Any) -> None:
    seen: list[str] = []
    _install(monkeypatch, lambda m: _ok("ok"), seen)
    caller = VeyaTextCaller("slow-free,good-model")
    veya_caller._CANDIDATE_COOLDOWN_UNTIL.update({"slow-free": 1e18, "good-model": 1e18})
    assert _call(caller)["content"] == "ok"
    assert seen == ["slow-free"]
    assert "slow-free" not in veya_caller._CANDIDATE_COOLDOWN_UNTIL
