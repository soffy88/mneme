"""阿里云 Qwen-VL VLM caller（拍卷 OCR 用）。mock httpx，不真连 DashScope——
验证请求组装（base64→data URI、多模态 content 结构）+ 响应解析（DashScope
output.choices[0].message.content 列表 → 文本 → JSON），接口与内核 VLM 一致。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.providers.qwenvl_caller import QwenVLCaller, _extract_json


def test_extract_json_handles_fenced_and_bare():
    assert _extract_json('```json\n{"a":1}\n```') == {"a": 1}
    assert _extract_json('{"b":2}') == {"b": 2}
    assert _extract_json("not json") == "not json"


def _fake_dashscope_response(text: str):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(
        return_value={
            "output": {"choices": [{"message": {"content": [{"text": text}]}}]},
            "usage": {"input_tokens": 11, "output_tokens": 22},
        }
    )
    return resp


@pytest.mark.asyncio
async def test_qwenvl_parses_json_ocr_response():
    caller = QwenVLCaller(api_key="sk-test", model="qwen-vl-max")
    ocr_json = '{"questions":[{"no":"1","question_text":"1+1=?","student_steps":[]}]}'

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_fake_dashscope_response(ocr_json))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        r = await caller(prompt="OCR这张卷子", image_b64="AAAA", response_format="json")

    # 响应形状与内核 VLM 契约一致
    assert isinstance(r["content"], dict)
    assert r["content"]["questions"][0]["no"] == "1"
    assert r["usage"]["input_tokens"] == 11

    # 请求组装：base64 被包成 data URI，content 是 [image, text]
    sent = mock_client.post.call_args.kwargs["json"]
    parts = sent["input"]["messages"][0]["content"]
    assert parts[0]["image"] == "data:image/jpeg;base64,AAAA"
    assert parts[1]["text"] == "OCR这张卷子"
    assert sent["model"] == "qwen-vl-max"


@pytest.mark.asyncio
async def test_qwenvl_passes_through_existing_data_uri():
    caller = QwenVLCaller(api_key="sk-test")
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_fake_dashscope_response("hi"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        r = await caller(prompt="p", image_b64="data:image/png;base64,ZZZ")

    sent = mock_client.post.call_args.kwargs["json"]
    assert (
        sent["input"]["messages"][0]["content"][0]["image"]
        == "data:image/png;base64,ZZZ"
    )
    assert r["content"] == "hi"  # 非 json 模式返回原文
