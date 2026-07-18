"""rag_client —— C4（W2C）Stratum 检索客户端：懒登录 + 检索，fail-safe 降级。

不用真网络（对照仓库既有惯例：qualitative_verifier 等一律注入假 LLM/HTTP，真实
连通性验证是一次性脚本，非常驻 pytest）——monkeypatch httpx.AsyncClient。
"""

from __future__ import annotations

import httpx
import pytest

import services.rag_client as rag_client


@pytest.fixture(autouse=True)
def _reset_token_cache():
    rag_client._token_cache.clear()
    yield
    rag_client._token_cache.clear()


class _FakeResponse:
    def __init__(self, status_code: int, json_data: dict):
        self.status_code = status_code
        self._json = json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=httpx.Request("POST", "http://x"),
                response=self,  # type: ignore[arg-type]
            )

    def json(self) -> dict:
        return self._json


class _FakeAsyncClient:
    def __init__(
        self, calls: list, login_response=None, search_response=None, raise_on=None
    ):
        self._calls = calls
        self._login_response = login_response
        self._search_response = search_response
        self._raise_on = raise_on

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, json=None, headers=None):
        self._calls.append({"url": url, "json": json, "headers": headers})
        if self._raise_on and self._raise_on in url:
            raise RuntimeError("network down")
        if "/api/auth/login" in url:
            return self._login_response
        return self._search_response


def _patch_client(monkeypatch, **kwargs):
    calls: list = []

    def factory(*args, **kw):
        return _FakeAsyncClient(calls, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return calls


@pytest.mark.asyncio
async def test_search_returns_empty_without_credentials(monkeypatch):
    monkeypatch.delenv("STRATUM_SERVICE_EMAIL", raising=False)
    monkeypatch.delenv("STRATUM_SERVICE_PASSWORD", raising=False)
    result = await rag_client.search("函数")
    assert result == []


@pytest.mark.asyncio
async def test_search_happy_path_logs_in_then_searches(monkeypatch):
    monkeypatch.setenv("STRATUM_SERVICE_EMAIL", "svc@x.com")
    monkeypatch.setenv("STRATUM_SERVICE_PASSWORD", "pw")
    calls = _patch_client(
        monkeypatch,
        login_response=_FakeResponse(
            200, {"access_token": "tok123", "expires_in": 900}
        ),
        search_response=_FakeResponse(
            200,
            {
                "results": [
                    {
                        "id": "1",
                        "type": "doc",
                        "title": "函数概念",
                        "score": 0.9,
                        "highlight": "…定义域…",
                    }
                ],
                "query_used": "函数",
            },
        ),
    )

    result = await rag_client.search("函数", top_k=3)

    assert result == [
        {"id": "1", "title": "函数概念", "highlight": "…定义域…", "score": 0.9}
    ]
    assert calls[0]["url"].endswith("/api/auth/login")
    assert calls[1]["url"].endswith("/api/search")
    assert calls[1]["headers"]["Authorization"] == "Bearer tok123"


@pytest.mark.asyncio
async def test_search_caches_token_across_calls(monkeypatch):
    monkeypatch.setenv("STRATUM_SERVICE_EMAIL", "svc@x.com")
    monkeypatch.setenv("STRATUM_SERVICE_PASSWORD", "pw")
    calls = _patch_client(
        monkeypatch,
        login_response=_FakeResponse(
            200, {"access_token": "tok123", "expires_in": 900}
        ),
        search_response=_FakeResponse(200, {"results": [], "query_used": "x"}),
    )

    await rag_client.search("第一次")
    await rag_client.search("第二次")

    login_calls = [c for c in calls if c["url"].endswith("/api/auth/login")]
    assert len(login_calls) == 1  # 第二次复用缓存 token，不重新登录


@pytest.mark.asyncio
async def test_search_returns_empty_on_login_failure(monkeypatch):
    monkeypatch.setenv("STRATUM_SERVICE_EMAIL", "svc@x.com")
    monkeypatch.setenv("STRATUM_SERVICE_PASSWORD", "wrong")
    _patch_client(
        monkeypatch, login_response=_FakeResponse(401, {"detail": "bad creds"})
    )

    result = await rag_client.search("函数")
    assert result == []


@pytest.mark.asyncio
async def test_search_returns_empty_on_network_error(monkeypatch):
    monkeypatch.setenv("STRATUM_SERVICE_EMAIL", "svc@x.com")
    monkeypatch.setenv("STRATUM_SERVICE_PASSWORD", "pw")
    _patch_client(
        monkeypatch,
        login_response=_FakeResponse(
            200, {"access_token": "tok123", "expires_in": 900}
        ),
        raise_on="/api/search",
    )

    result = await rag_client.search("函数")
    assert result == []
