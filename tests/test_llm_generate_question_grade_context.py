"""_llm_generate_question 年级上下文修复验收。

真实事故（W3 B-8 补测撞见，见 outputs/W3-PENDING-ITEMS.md）：一年级 KC
「1～5的认识」走 LLM 兜底出题时，生成了"集合论与数理逻辑的皮亚诺公理体系
背景下……冯·诺依曼序数……"这种研究生水平的题——根因是
_llm_generate_question 之前只传知识点名字，硬编码"适合中学生"，LLM 没有
任何真实年级信号。

两层验收：
1. 单测 _llm_generate_question 本身——mock QwenTextCaller，断言组装出的
   prompt 里含正确的学段描述、不再是硬编码的"适合中学生"。
2. 端到端过 tool_request_question——用真实撞过这个 bug 的那个 G1 KU
   （RENJIAO-G1-MATH-S-ku-1-5的认识），mock _llm_generate_question 本身
   （不真的调 LLM），断言它被调用时拿到的 grade 参数确实是从真实
   Textbook.grade 联表查出来的 "G1"，不是 None/硬编码。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("mneme_core")

from obase.db import SessionLocal  # noqa: E402
from services.mcp_router import _GRADE_ZH, _llm_generate_question  # noqa: E402
from services.models import User, UserRole  # noqa: E402

# 真实撞过原始 bug 的 G1 KU——41 条 wrong_questions 引用它，但题库过滤器
# 硬编码只认 profiler_analysis.grade=="高一"，所以这个 G1 KU 的真实请求会
# 可靠地落到 LLM 兜底分支（同原始事故的真实触发路径一致）。
G1_KU_WITH_HARDCODED_HIGH_SCHOOL_BANK_FILTER = "RENJIAO-G1-MATH-S-ku-1-5的认识"


def _fake_caller(captured: list):
    async def call(*, messages, max_tokens=512, response_format=None, **kwargs):
        captured.append(messages)
        return {
            "content": '{"prompt":"1、2、3、4、5，哪个数字最大？","answer":"5","qtype":"solve"}'
        }

    return call


@pytest.mark.asyncio
async def test_grade_g1_produces_elementary_level_prompt_not_generic_middle_school():
    captured: list = []
    with (
        patch(
            "services.providers.qwenvl_caller.QwenTextCaller",
            return_value=_fake_caller(captured),
        ),
        patch(
            "os.environ.get",
            side_effect=lambda k, d=None: "fake-key" if k == "DASHSCOPE_API_KEY" else d,
        ),
    ):
        result = await _llm_generate_question("1～5的认识", grade="G1")

    assert result is not None
    assert len(captured) == 1
    prompt_text = captured[0][0]["content"]
    assert _GRADE_ZH["G1"] in prompt_text  # "小学一年级" 真的出现在 prompt 里
    assert "适合中学生" not in prompt_text  # 旧的硬编码错误措辞不再出现


@pytest.mark.asyncio
async def test_grade_g10_produces_high_school_level_prompt():
    captured: list = []
    with (
        patch(
            "services.providers.qwenvl_caller.QwenTextCaller",
            return_value=_fake_caller(captured),
        ),
        patch(
            "os.environ.get",
            side_effect=lambda k, d=None: "fake-key" if k == "DASHSCOPE_API_KEY" else d,
        ),
    ):
        result = await _llm_generate_question("二次函数的零点", grade="G10")

    assert result is not None
    prompt_text = captured[0][0]["content"]
    assert _GRADE_ZH["G10"] in prompt_text  # "高一"


@pytest.mark.asyncio
async def test_unknown_grade_degrades_to_generic_label_not_crash():
    """grade=None（联表查不到 Textbook 行的边界情况）必须优雅降级，不崩，
    也不能悄悄用回旧的"适合中学生"硬编码——用更中性的"中小学"兜底。"""
    captured: list = []
    with (
        patch(
            "services.providers.qwenvl_caller.QwenTextCaller",
            return_value=_fake_caller(captured),
        ),
        patch(
            "os.environ.get",
            side_effect=lambda k, d=None: "fake-key" if k == "DASHSCOPE_API_KEY" else d,
        ),
    ):
        result = await _llm_generate_question("某知识点", grade=None)

    assert result is not None
    prompt_text = captured[0][0]["content"]
    assert "适合中学生" not in prompt_text


@pytest.mark.asyncio
async def test_end_to_end_real_g1_ku_passes_real_grade_to_fallback():
    """端到端：真实撞过原始 bug 的 G1 KU，经 tool_request_question 真实
    联表查询，确认传给 _llm_generate_question 的 grade 确实是 "G1"（不是
    None/不是硬编码），不需要真的打 LLM。"""
    from services.mcp_router import tool_request_question

    sid = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
        await db.flush()

        with patch(
            "services.mcp_router._llm_generate_question",
            new=AsyncMock(
                return_value={"prompt": "x", "expected": "y", "qtype": "solve"}
            ),
        ) as mock_gen:
            await tool_request_question(
                db, sid, G1_KU_WITH_HARDCODED_HIGH_SCHOOL_BANK_FILTER
            )

        assert mock_gen.await_args is not None
        _, kwargs = mock_gen.await_args
        assert kwargs.get("grade") == "G1"
