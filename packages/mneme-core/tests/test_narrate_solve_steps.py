"""Tests for narrate_solve_steps (W4 Solve §2 — 讲解层).

SV-2/SV-4 红线：narration 是纯附加字段，本元素自身绝不修改/替换传入的
answer/steps——这里只测本元素自身的行为（返回值确实只是一个 str，不改变
调用方传进来的 answer/steps 变量本身），端到端"最终响应里 answer/steps
仍是内核原始输出"的断言见 tests/test_solve_problem_omodul.py。
"""

from __future__ import annotations

import pytest

from mneme_core.oskill.narrate_solve_steps import narrate_solve_steps

STEPS = [
    {
        "step_number": 1,
        "description": "Parse expression",
        "expression": "x**2-4",
        "result": "x**2-4",
    },
    {
        "step_number": 2,
        "description": "Find zeros (solve f(x)=0)",
        "expression": "solve(x**2-4, x)",
        "result": "[-2, 2]",
    },
]
ANSWER = "zeros: [-2, 2]"


def _caller(content: str):
    async def call(*, messages, system=None, max_tokens=800):
        assert isinstance(messages, list) and messages
        return {"content": content}

    return call


def _raising_caller():
    async def call(*, messages, system=None, max_tokens=800):
        raise RuntimeError("provider down")

    return call


@pytest.mark.asyncio
async def test_happy_path_returns_llm_narration():
    llm = _caller("这道题是求二次函数的零点，答案是 x=-2 或 x=2。")
    narration = await narrate_solve_steps(
        llm, kernel="function", task="zeros", answer=ANSWER, steps=STEPS
    )
    assert narration == "这道题是求二次函数的零点，答案是 x=-2 或 x=2。"


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_reading_steps_verbatim():
    llm = _raising_caller()
    narration = await narrate_solve_steps(
        llm, kernel="function", task="zeros", answer=ANSWER, steps=STEPS
    )
    assert narration != ""
    # 兜底内容必须来自真实 steps/answer，不是空话
    assert "Parse expression" in narration
    assert ANSWER in narration


@pytest.mark.asyncio
async def test_empty_llm_response_falls_back():
    llm = _caller("")
    narration = await narrate_solve_steps(
        llm, kernel="function", task="zeros", answer=ANSWER, steps=STEPS
    )
    assert narration != ""
    assert ANSWER in narration


@pytest.mark.asyncio
async def test_no_steps_and_no_answer_returns_empty():
    """无东西可讲时不硬凑内容（不可解的题不应该有"讲解"）。"""
    llm = _caller("不应该被调用")
    narration = await narrate_solve_steps(
        llm, kernel="function", task="zeros", answer="", steps=[]
    )
    assert narration == ""
