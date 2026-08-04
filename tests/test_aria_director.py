"""Aria Director `direct` 行为测试：无 key 回落启发式 + LLM 路径解析 + 异常兜底。

CRG 审查发现 direct 只在 test_aria_brain.py 里被 patch 掉，从未真正执行过；
`/v1/aria/act` 路由也无直接测试。这里锁三层行为：无 key 回落、LLM 合法输出、
LLM 异常兜底（llm_fail）。不写掌握度、不碰网络（caller 全 mock）。"""

from __future__ import annotations

import pytest

from services.aria_director import (
    AriaDirectorInput,
    _parse_json,
    direct,
)


def _no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)


# ── 无 key → 启发式回落 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_direct_falls_back_to_heuristic_without_key(monkeypatch):
    _no_key(monkeypatch)
    out = await direct(AriaDirectorInput(event="wake"))
    assert out.source == "heuristic"
    assert out.action == "speak"
    assert out.utterance and "Aria" in out.utterance


@pytest.mark.asyncio
async def test_direct_falls_back_with_key_invalid_placeholder(monkeypatch):
    monkeypatch.setenv("QWEN_API_KEY", "your_key_here")
    out = await direct(AriaDirectorInput(event="tick"))
    assert out.source == "heuristic"
    assert out.action in ("play_piano", "speak")


# ── LLM 路径 ─────────────────────────────────────────────────────────────────


class _FakeCaller:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def __call__(self, **kwargs):
        return self._payload


def _patch_caller(monkeypatch: pytest.MonkeyPatch, content: str):
    from services.providers import qwenvl_caller

    monkeypatch.setattr(qwenvl_caller, "QwenTextCaller", lambda **kw: _FakeCaller({"content": content}))


@pytest.mark.asyncio
async def test_direct_llm_valid_output(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    _patch_caller(
        monkeypatch,
        '{"action":"play_piano","utterance":null,"emotion":"focused","hold_ms":4000,"reason":"llm"}',
    )
    out = await direct(AriaDirectorInput(event="tick"))
    assert out.source == "llm"
    assert out.action == "play_piano"
    assert out.reason == "llm"


@pytest.mark.asyncio
async def test_direct_llm_sanitizes_action_and_hold(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    _patch_caller(
        monkeypatch,
        '{"action":"fly","utterance":"hi","emotion":"warm","hold_ms":999999,"reason":"r"}',
    )
    out = await direct(AriaDirectorInput(event="tick"))
    # 非法 action → tick 回落 play_piano；hold 被钳制到上限
    assert out.action == "play_piano"
    assert out.hold_ms <= 12000


@pytest.mark.asyncio
async def test_direct_llm_speak_without_utterance_fills_heuristic(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    _patch_caller(
        monkeypatch,
        '{"action":"speak","utterance":null,"emotion":"warm","hold_ms":3000,"reason":"r"}',
    )
    out = await direct(AriaDirectorInput(event="user_message", message="hello"))
    assert out.action == "speak"
    assert out.utterance  # 从启发式兜底补齐


@pytest.mark.asyncio
async def test_direct_llm_exception_falls_back_to_heuristic(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    from services.providers import qwenvl_caller

    class _RaisingCaller:
        async def __call__(self, **kwargs):
            raise RuntimeError("upstream down")

    monkeypatch.setattr(qwenvl_caller, "QwenTextCaller", lambda **kw: _RaisingCaller())
    out = await direct(AriaDirectorInput(event="wake"))
    assert out.source == "heuristic"
    assert out.reason.startswith("llm_fail:")
    assert out.action == "speak"


# ── _parse_json 韧性 ─────────────────────────────────────────────────────────


def test_parse_json_fenced():
    assert _parse_json('```json\n{"action":"speak"}\n```') == {"action": "speak"}


def test_parse_json_embedded_in_text():
    assert _parse_json('Sure! Here: {"action":"think","hold_ms":2000} thanks') == {
        "action": "think",
        "hold_ms": 2000,
    }


def test_parse_json_garbage_returns_empty():
    assert _parse_json("not json at all") == {}
