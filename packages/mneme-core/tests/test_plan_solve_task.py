"""Tests for plan_solve_task (W4 Solve §2 — 题意理解层).

Same convention as test_book_engine_b1.py: scripted fake async LLMCaller,
zero provider dependency.
"""

from __future__ import annotations

import json

import pytest

from mneme_core.oskill.plan_solve_task import plan_solve_task


def _caller(payload):
    async def call(*, messages, system=None, max_tokens=800):
        assert isinstance(messages, list) and messages
        content = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False)
        )
        return {"content": content}

    return call


def _raising_caller():
    async def call(*, messages, system=None, max_tokens=800):
        raise RuntimeError("provider down")

    return call


@pytest.mark.asyncio
async def test_happy_path_valid_kernel_and_task():
    llm = _caller(
        {
            "kernel": "function",
            "task": "zeros",
            "params": {"expression": "x**2-4", "variable": "x"},
            "restated_problem": "求 x^2-4=0 的解",
        }
    )
    plan = await plan_solve_task(llm, problem_text="求 x^2-4=0 的解")
    assert plan.error == ""
    assert plan.kernel == "function"
    assert plan.task == "zeros"
    assert plan.params == {"expression": "x**2-4", "variable": "x"}
    assert plan.restated_problem == "求 x^2-4=0 的解"


@pytest.mark.asyncio
async def test_kernel_not_in_registry_is_rejected_not_guessed():
    """LLM 编造一个不存在的内核名字——必须拒绝，不能猜一个"看起来最接近"的
    内核硬凑（那样求解结果会文不对题，比明确报错更危险）。"""
    llm = _caller(
        {
            "kernel": "calculus_solver",  # 不存在
            "task": "zeros",
            "params": {},
            "restated_problem": "x",
        }
    )
    plan = await plan_solve_task(llm, problem_text="随便一道题")
    assert plan.error != ""
    assert plan.kernel == ""


@pytest.mark.asyncio
async def test_task_not_supported_by_kernel_is_rejected():
    llm = _caller(
        {
            "kernel": "function",
            "task": "not_a_real_task",
            "params": {"expression": "x"},
            "restated_problem": "x",
        }
    )
    plan = await plan_solve_task(llm, problem_text="随便一道题")
    assert plan.error != ""


@pytest.mark.asyncio
async def test_conic_kernel_has_no_task_requirement():
    """solve_conic 没有 task 参数——空字符串合法，不应被误判为"不支持的 task"。"""
    llm = _caller(
        {
            "kernel": "conic",
            "task": "",
            "params": {"expression": "x^2+y^2=25"},
            "restated_problem": "圆的方程",
        }
    )
    plan = await plan_solve_task(llm, problem_text="x^2+y^2=25 是什么图形")
    assert plan.error == ""
    assert plan.kernel == "conic"


@pytest.mark.asyncio
async def test_llm_exception_returns_error_plan_not_raise():
    llm = _raising_caller()
    plan = await plan_solve_task(llm, problem_text="随便一道题")
    assert plan.error != ""
    assert plan.kernel == ""


@pytest.mark.asyncio
async def test_unparseable_llm_output_returns_error_plan():
    llm = _caller("这不是 JSON，是一段自然语言废话")
    plan = await plan_solve_task(llm, problem_text="随便一道题")
    assert plan.error != ""


@pytest.mark.asyncio
async def test_json_wrapped_in_markdown_fence_still_parses():
    """真实 provider 实测偶发行为：不总是严格只输出裸 JSON，有时会包一层
    ```json ... ``` code fence——这条测试防止这个真实发生过的解析失败
    回归（本地 fake caller 默认输出干净 JSON，不会自然暴露这个问题）。"""
    payload = {
        "kernel": "function",
        "task": "zeros",
        "params": {"expression": "x**2-4", "variable": "x"},
        "restated_problem": "求 x^2-4=0 的解",
    }
    llm = _caller("```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```")
    plan = await plan_solve_task(llm, problem_text="求 x^2-4=0 的解")
    assert plan.error == ""
    assert plan.kernel == "function"
    assert plan.task == "zeros"


@pytest.mark.asyncio
async def test_json_with_surrounding_prose_still_parses():
    """LLM 在 JSON 前后加了解释性文字（未严格遵守"只能输出 JSON"的指令）时，
    仍能提取出中间的 JSON 子串。"""
    payload = {
        "kernel": "conic",
        "task": "",
        "params": {"expression": "x^2+y^2=25"},
        "restated_problem": "圆的方程",
    }
    llm = _caller(
        "好的，这是我的分析：\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\n以上就是结果。"
    )
    plan = await plan_solve_task(llm, problem_text="x^2+y^2=25")
    assert plan.error == ""
    assert plan.kernel == "conic"


@pytest.mark.asyncio
async def test_non_dict_params_coerced_to_empty_dict():
    llm = _caller(
        {
            "kernel": "function",
            "task": "zeros",
            "params": "not a dict",
            "restated_problem": "x",
        }
    )
    plan = await plan_solve_task(llm, problem_text="随便一道题")
    assert plan.error == ""
    assert plan.params == {}
