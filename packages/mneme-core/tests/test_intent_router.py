"""Tests for oprim.intent_router — C1 (W2C). Fake LLM injected, no real network call."""

import pytest

from mneme_core.oprim.intent_router import ChatIntent, classify_chat_intent


def _fake_llm(response: str):
    async def llm(prompt: str) -> str:
        del prompt
        return response

    return llm


@pytest.mark.asyncio
async def test_classifies_practice_with_kc_hint():
    llm = _fake_llm('{"mode": "practice", "kc_hint": "函数"}')
    result = await classify_chat_intent("我想练函数", llm=llm)
    assert result == ChatIntent(mode="practice", kc_hint="函数")


@pytest.mark.asyncio
async def test_classifies_free_qa():
    llm = _fake_llm('{"mode": "free_qa", "kc_hint": null}')
    result = await classify_chat_intent("什么是函数？", llm=llm)
    assert result == ChatIntent(mode="free_qa", kc_hint=None)


@pytest.mark.asyncio
async def test_handles_markdown_fenced_json():
    llm = _fake_llm('```json\n{"mode": "practice", "kc_hint": null}\n```')
    result = await classify_chat_intent("考我一下", llm=llm)
    assert result.mode == "practice"


@pytest.mark.asyncio
async def test_falls_back_to_free_qa_on_invalid_json():
    llm = _fake_llm("not json at all")
    result = await classify_chat_intent("随便说点什么", llm=llm)
    assert result == ChatIntent(mode="free_qa")


@pytest.mark.asyncio
async def test_falls_back_to_free_qa_on_illegal_mode_value():
    llm = _fake_llm('{"mode": "something_else"}')
    result = await classify_chat_intent("...", llm=llm)
    assert result == ChatIntent(mode="free_qa")


@pytest.mark.asyncio
async def test_falls_back_to_free_qa_on_llm_exception():
    async def broken_llm(prompt: str) -> str:
        del prompt
        raise RuntimeError("network down")

    result = await classify_chat_intent("...", llm=broken_llm)
    assert result == ChatIntent(mode="free_qa")


@pytest.mark.asyncio
async def test_missing_kc_hint_defaults_to_none():
    llm = _fake_llm('{"mode": "practice"}')
    result = await classify_chat_intent("我想练习", llm=llm)
    assert result.kc_hint is None
