"""阿里云通义千问 caller（文本 QwenTextCaller + 视觉 QwenVLCaller），走 OpenAI
兼容端点。mock httpx，不真连——验证请求组装（image_url data URI、多模态 content）
+ 响应解析（choices[0].message.content），接口与内核 LLM/VLM 契约一致。
真实端到端（文本 qwen3.7-plus / 视觉 qwen-vl-max）已在配 key 后手动实测通过。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.providers.qwenvl_caller import QwenTextCaller, QwenVLCaller, _extract_json


def test_extract_json_handles_fenced_and_bare():
    assert _extract_json('```json\n{"a":1}\n```') == {"a": 1}
    assert _extract_json('{"b":2}') == {"b": 2}
    assert _extract_json("not json") == "not json"


def _fake_openai_response(text: str):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(
        return_value={
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 22},
        }
    )
    return resp


def _mock_client(resp):
    c = AsyncMock()
    c.post = AsyncMock(return_value=resp)
    c.__aenter__ = AsyncMock(return_value=c)
    c.__aexit__ = AsyncMock(return_value=False)
    return c


@pytest.mark.asyncio
async def test_text_caller_shapes_request_and_response(monkeypatch):
    monkeypatch.setenv("QWEN_BASE_URL", "https://maas.example.com/compatible-mode/v1")
    caller = QwenTextCaller(api_key="sk-test", model="qwen3.7-plus")
    client = _mock_client(_fake_openai_response("你好世界"))
    with patch("httpx.AsyncClient", return_value=client):
        r = await caller(messages=[{"role": "user", "content": "hi"}], system="s")
    assert r["content"] == "你好世界"
    assert r["usage"]["input_tokens"] == 11
    # base_url 生效 + system 前插
    url = client.post.call_args.args[0]
    assert url == "https://maas.example.com/compatible-mode/v1/chat/completions"
    sent = client.post.call_args.kwargs["json"]
    assert sent["model"] == "qwen3.7-plus"
    assert sent["messages"][0] == {"role": "system", "content": "s"}


@pytest.mark.asyncio
async def test_vl_caller_parses_json_ocr_response():
    caller = QwenVLCaller(api_key="sk-test", model="qwen-vl-max")
    ocr_json = '{"questions":[{"no":"1","question_text":"1+1=?","student_steps":[]}]}'
    client = _mock_client(_fake_openai_response(ocr_json))
    with patch("httpx.AsyncClient", return_value=client):
        r = await caller(prompt="OCR", image_b64="AAAA", response_format="json")

    assert isinstance(r["content"], dict)
    assert r["content"]["questions"][0]["no"] == "1"
    assert r["usage"]["input_tokens"] == 11

    # 请求：OpenAI image_url data URI + [text, image_url]
    sent = client.post.call_args.kwargs["json"]
    parts = sent["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "OCR"}
    assert parts[1]["image_url"]["url"] == "data:image/jpeg;base64,AAAA"


@pytest.mark.asyncio
async def test_vl_caller_passes_through_existing_data_uri():
    caller = QwenVLCaller(api_key="sk-test")
    client = _mock_client(_fake_openai_response("hi"))
    with patch("httpx.AsyncClient", return_value=client):
        r = await caller(prompt="p", image_b64="data:image/png;base64,ZZZ")
    sent = client.post.call_args.kwargs["json"]
    assert (
        sent["messages"][0]["content"][1]["image_url"]["url"]
        == "data:image/png;base64,ZZZ"
    )
    assert r["content"] == "hi"  # 非 json 模式返回原文
