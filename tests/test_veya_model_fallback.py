"""Veya 模型名单回退的回归测试。

钉的是一个**实测**行为：网关用 HTTP 200 把上游故障当正文返回
（`{"content": "gpt-5.6-luna 兜底失败"}`）。所以：

- 只判异常/状态码 → 每个模型都「成功」→ 回退永远不触发（这是第一版的错法）；
- 必须**看返回内容**才能识别失效模型并换下一个。

也钉住「全废时要抛异常且带上每个模型的失败原因」——不能静默返回空内容，
那会让上层把「没有生成」当成「生成成功但内容为空」。
"""

from __future__ import annotations

import asyncio

import pytest

from services.providers.veya_caller import VeyaTextCaller, looks_like_gateway_error


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self._payload


class _Client:
    """按模型名记录调用并返回预设结果；httpx.AsyncClient 的替身。"""

    def __init__(self, results):
        self.results = results
        self.seen: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        self.seen.append(json["model"])
        r = self.results.get(json["model"])
        if isinstance(r, Exception):
            raise r
        return _Resp({"choices": [{"message": {"content": r}}], "usage": {}})


def _stub_httpx(monkeypatch, client_cls):
    """把 httpx 换成只含本路径用到的成员的替身。

    `provider_httpx_timeout()` 会读 `httpx.Timeout`，第一版替身没给这个属性，
    于是 3 个测试死在装配超时上而不是走到回退逻辑。
    """
    import sys

    module = type(
        "m",
        (),
        {
            "AsyncClient": lambda **kw: client_cls(),
            "Timeout": lambda **kw: object(),
        },
    )
    monkeypatch.setitem(sys.modules, "httpx", module)


def _call(caller, monkeypatch):
    """直接跑 __call__ 内部逻辑（httpx 被替换）。"""
    return asyncio.run(
        caller(
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=8,
        )
    )


def test_error_markers_detect_gateway_payload():
    assert looks_like_gateway_error("gpt-5.6-luna 兜底失败") is True
    assert looks_like_gateway_error("opencode-go rejected the request (HTTP 429)") is True
    assert looks_like_gateway_error("Go usage limit exceeded") is True
    assert looks_like_gateway_error("PONG") is False
    assert looks_like_gateway_error("") is False
    assert looks_like_gateway_error(None) is False


def test_single_model_keeps_original_behaviour(monkeypatch):
    monkeypatch.setenv("VEYA_MODEL", "veya1.2")
    c = VeyaTextCaller()
    assert c.models == ["veya1.2"]
    assert c.model == "veya1.2"  # 别处会读这个字段记审计


def test_falls_back_past_http200_error_payload(monkeypatch):
    """核心：第一个模型 HTTP 200 但正文是错误串 → 必须换下一个。"""
    monkeypatch.setenv("VEYA_MODEL", "veya1.2,veya1.1,veya-deepseek-v4-flash-nv")
    c = VeyaTextCaller()
    seen = []

    class _C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            seen.append(json["model"])
            body = {
                "veya1.2": "gpt-5.6-luna 兜底失败",
                "veya1.1": "gpt-5.6-luna 兜底失败",
                "veya-deepseek-v4-flash-nv": "PONG",
            }[json["model"]]
            return _Resp({"choices": [{"message": {"content": body}}], "usage": {}})

    _stub_httpx(monkeypatch, _C)
    out = _call(c, monkeypatch)
    assert out["content"] == "PONG"
    assert seen == ["veya1.2", "veya1.1", "veya-deepseek-v4-flash-nv"]
    assert c.last_good_model == "veya-deepseek-v4-flash-nv"


def test_falls_back_past_transport_error(monkeypatch):
    monkeypatch.setenv("VEYA_MODEL", "a,b")
    c = VeyaTextCaller()
    calls = []

    class _C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            calls.append(json["model"])
            if json["model"] == "a":
                raise RuntimeError("connection refused")
            return _Resp({"choices": [{"message": {"content": "OK"}}], "usage": {}})

    _stub_httpx(monkeypatch, _C)
    assert _call(c, monkeypatch)["content"] == "OK"
    assert calls == ["a", "b"]


def test_all_candidates_failing_raises_with_reasons(monkeypatch):
    """全废必须抛异常并带上每个模型的原因 —— 不能静默返回空内容。"""
    monkeypatch.setenv("VEYA_MODEL", "x,y")
    c = VeyaTextCaller()

    class _C:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            return _Resp({"choices": [{"message": {"content": "兜底失败"}}], "usage": {}})

    _stub_httpx(monkeypatch, _C)
    with pytest.raises(RuntimeError) as ei:
        _call(c, monkeypatch)
    msg = str(ei.value)
    assert "all VEYA_MODEL candidates failed" in msg
    assert "x: gateway_error_payload" in msg
    assert "y: gateway_error_payload" in msg


def test_empty_list_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("VEYA_MODEL", " , , ")
    assert VeyaTextCaller().models == ["veya1.2-128K"]
