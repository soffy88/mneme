"""本机 Veya caller 的 OpenAI-compatible 请求/响应契约测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.providers.veya_caller import VeyaTextCaller, VeyaVLCaller


def _response(content: str) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(
        return_value={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5},
        }
    )
    return response


def _client(response: MagicMock) -> AsyncMock:
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_veya_text_caller_uses_local_model_and_parses_response(monkeypatch):
    monkeypatch.setenv("VEYA_BASE_URL", "http://veya.test/v1")
    caller = VeyaTextCaller(model="veya1.2-128K")
    client = _client(_response("好"))

    with patch("httpx.AsyncClient", return_value=client):
        result = await caller(
            messages=[{"role": "user", "content": "hi"}], system="你是老师"
        )

    assert result["content"] == "好"
    assert result["usage"] == {"input_tokens": 3, "output_tokens": 5}
    assert client.post.call_args.args[0] == "http://veya.test/v1/chat/completions"
    payload = client.post.call_args.kwargs["json"]
    assert payload["model"] == "veya1.2-128K"
    assert payload["messages"][0] == {"role": "system", "content": "你是老师"}


@pytest.mark.asyncio
async def test_veya_vl_caller_sends_image_and_unfences_json(monkeypatch):
    monkeypatch.setenv("VEYA_BASE_URL", "http://veya.test/v1")
    caller = VeyaVLCaller(model="veya1.2-vl")
    client = _client(_response('```json\n{"color":"red"}\n```'))

    with patch("httpx.AsyncClient", return_value=client):
        result = await caller(
            prompt="识别主色", image_b64="AAAA", response_format="json"
        )

    assert result["content"] == {"color": "red"}
    payload = client.post.call_args.kwargs["json"]
    assert payload["model"] == "veya1.2-vl"
    parts = payload["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "识别主色"}
    assert parts[1]["image_url"]["url"] == "data:image/jpeg;base64,AAAA"
