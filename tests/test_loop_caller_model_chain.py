"""VeyaLoopCaller / OpenAICompatibleLoopCaller：逗号分隔的 VEYA_MODEL 候选链逐个尝试（修复整串当模型名 → 网关 400）。"""

import httpx
import pytest

from mneme_agent.qwen_llm import OpenAICompatibleLoopCaller, model_chain


def test_model_chain():
    assert model_chain("a, b ,c") == ["a", "b", "c"]
    assert model_chain("veya1.2") == ["veya1.2"]


async def test_falls_back_to_next_model(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        m = json.loads(request.content)["model"]
        seen.append(m)
        if m == "bad":
            return httpx.Response(400, json={"error": {"message": "unknown model"}})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "2"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    real = httpx.AsyncClient

    def fake_client(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return real(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    c = OpenAICompatibleLoopCaller(api_key="k", model="bad,good", base_url="http://gw/v1")
    out = await c(messages=[{"role": "user", "content": "1+1"}])
    assert seen == ["bad", "good"] and out


async def test_all_fail_raises(monkeypatch):
    real = httpx.AsyncClient

    def fake_client(*a, **k):
        k["transport"] = httpx.MockTransport(lambda r: httpx.Response(400, json={}))
        return real(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    c = OpenAICompatibleLoopCaller(api_key="k", model="x,y", base_url="http://gw/v1")
    with pytest.raises(httpx.HTTPStatusError):
        await c(messages=[{"role": "user", "content": "1+1"}])
