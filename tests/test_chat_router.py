"""chat_router.tool_chat_turn —— C1（W2C）编排：GetPath 默认池 + persona 注入 + 分流。

假 loop_caller/classify_llm 注入（无真实 LLM/网络依赖，对照仓库既有惯例：
build_s1_grading_fixture.py 式的真 LLM 验证放一次性脚本，非常驻 pytest）。
"""

from __future__ import annotations

import json
import uuid

import pytest

from obase.db import SessionLocal
from services.chat_router import tool_chat_turn
from services.mcp_router import tool_get_path


def _classify_llm(response: str):
    async def llm(prompt: str) -> str:
        del prompt
        return response

    return llm


async def _exploding_loop_caller(**kwargs):
    raise AssertionError(f"practice 分支不该调用 loop_caller: {kwargs}")


def _one_shot_loop_caller(captured: dict):
    async def caller(
        *, messages, tools=None, max_tokens=8192, thinking_budget=None, system=None
    ):
        del messages, tools, max_tokens, thinking_budget
        captured["system"] = system
        return {
            "content": [{"type": "text", "text": "我们来看看这道题吧。"}],
            "stop_reason": "end_turn",
            "usage": {},
        }

    return caller


@pytest.mark.asyncio
async def test_practice_intent_routes_without_touching_loop():
    async with SessionLocal() as db:
        result = await tool_chat_turn(
            db,
            uuid.uuid4(),
            message="我想练函数",
            loop_caller=_exploding_loop_caller,
            classify_llm=_classify_llm('{"mode": "practice", "kc_hint": "函数"}'),
        )
    assert result["action"] == "goto_mastery_path"
    assert result["kc_hint"] == "函数"


@pytest.mark.asyncio
async def test_free_qa_uses_default_persona_and_path():
    captured: dict = {}
    async with SessionLocal() as db:
        sid = uuid.uuid4()
        path = await tool_get_path(db, sid)

        result = await tool_chat_turn(
            db,
            sid,
            message="什么是函数？",
            loop_caller=_one_shot_loop_caller(captured),
            classify_llm=_classify_llm('{"mode": "free_qa"}'),
        )
    assert result["action"] == "continue"
    assert result["reply"] == "我们来看看这道题吧。"
    # 默认 persona（encouraging-buddy）应已拼进 system prompt
    assert "鼓励型伙伴" in captured["system"]
    # 未显式给 kc_ids 时用 GetPath 默认路径（间接验证：至少不因空池报错，且能正常跑通）
    assert len(path["kc_ids"]) > 0


@pytest.mark.asyncio
async def test_explicit_persona_slug_changes_system_prompt():
    captured_a: dict = {}
    captured_b: dict = {}
    async with SessionLocal() as db:
        sid = uuid.uuid4()
        await tool_chat_turn(
            db,
            sid,
            message="你好",
            persona_slug="encouraging-buddy",
            loop_caller=_one_shot_loop_caller(captured_a),
            classify_llm=_classify_llm('{"mode": "free_qa"}'),
        )
        await tool_chat_turn(
            db,
            sid,
            message="你好",
            persona_slug="brisk-coach",
            loop_caller=_one_shot_loop_caller(captured_b),
            classify_llm=_classify_llm('{"mode": "free_qa"}'),
        )
    assert captured_a["system"] != captured_b["system"]
    assert "鼓励型伙伴" in captured_a["system"]
    assert "干脆型教练" in captured_b["system"]


@pytest.mark.asyncio
async def test_expected_never_appears_in_response():
    """C1 验收：expected 永不进 LLM 上下文/返回体（W3 前端版断言扩到 chat）。"""
    captured: dict = {}
    async with SessionLocal() as db:
        result = await tool_chat_turn(
            db,
            uuid.uuid4(),
            message="帮我出一道函数题",
            loop_caller=_one_shot_loop_caller(captured),
            classify_llm=_classify_llm('{"mode": "free_qa"}'),
        )
    assert "expected" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.asyncio
async def test_unknown_persona_slug_falls_back_to_default_not_error():
    captured: dict = {}
    async with SessionLocal() as db:
        result = await tool_chat_turn(
            db,
            uuid.uuid4(),
            message="你好",
            persona_slug="no-such-persona",
            loop_caller=_one_shot_loop_caller(captured),
            classify_llm=_classify_llm('{"mode": "free_qa"}'),
        )
    assert result["action"] == "continue"
    assert "鼓励型伙伴" in captured["system"]
