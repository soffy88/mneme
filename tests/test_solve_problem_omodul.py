"""SV-2/SV-4 验收：omodul.solve_problem 端到端——求解步骤来自内核真实输出，
LLM 只转述、不参与求解/判分。

核心手法：用一个"恶意"的 fake caller，在讲解阶段刻意胡说八道、给出与内核
真实答案不同的数值结果——断言最终返回结构里的 answer/steps 仍然 100% 等于
内核的真实输出，不受讲解内容影响。这是比"读代码看起来对"更硬的证据：即使
LLM 的讲解文本本身是错的/编造的，返回给前端的权威字段也不会被污染。
"""

from __future__ import annotations

import json

import pytest

from omodul.solve_problem import SolveProblemConfig, SolveProblemInput, solve_problem


def _scripted_caller(plan_payload: dict, narration_text: str):
    """第一次调用（plan_solve_task）返回 plan_payload 的 JSON，第二次调用
    （narrate_solve_steps）返回 narration_text（可以是任意胡说八道的内容，
    用于验证它不会污染 answer/steps）。"""
    calls = {"n": 0}

    async def call(*, messages, system=None, max_tokens=800):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"content": json.dumps(plan_payload, ensure_ascii=False)}
        return {"content": narration_text}

    return call


@pytest.mark.asyncio
async def test_end_to_end_happy_path_all_stages_wired():
    caller = _scripted_caller(
        plan_payload={
            "kernel": "function",
            "task": "zeros",
            "params": {"expression": "x**2-4", "variable": "x"},
            "restated_problem": "求 x^2-4=0 的解",
        },
        narration_text="这道题是求二次函数的零点，答案是 x=-2 或 x=2。",
    )
    result = await solve_problem(
        config=SolveProblemConfig(),
        input_data=SolveProblemInput(problem_text="求 x^2-4=0 的解"),
        caller=caller,
    )
    assert result["status"] == "success"
    findings = result["findings"]
    assert findings["kernel"] == "function"
    assert findings["solvable"] is True
    assert findings["answer"] == "zeros: [-2, 2]"
    assert len(findings["steps"]) == 2
    assert findings["narration"] == "这道题是求二次函数的零点，答案是 x=-2 或 x=2。"
    # decision_trail 记录了每一步判断（B3 precedent 里同类要求）
    trail_steps = [t["step"] for t in result["decision_trail"]]
    assert trail_steps == ["plan_solve_task", "solve_dispatch", "narrate_solve_steps"]


@pytest.mark.asyncio
async def test_narration_cannot_override_kernel_answer_or_steps():
    """SV-4 核心断言：讲解阶段的 LLM 刻意"编造"一个不同的答案（说成 x=100），
    最终返回结构里的 answer 字段必须仍然是内核真实算出的 'zeros: [-2, 2]'，
    不能被讲解文本污染/替换。"""
    caller = _scripted_caller(
        plan_payload={
            "kernel": "function",
            "task": "zeros",
            "params": {"expression": "x**2-4", "variable": "x"},
            "restated_problem": "求 x^2-4=0 的解",
        },
        narration_text="这道题答案是 x=100（这是故意编造的错误讲解，用于测试）。",
    )
    result = await solve_problem(
        config=SolveProblemConfig(),
        input_data=SolveProblemInput(problem_text="求 x^2-4=0 的解"),
        caller=caller,
    )
    findings = result["findings"]
    # answer/steps 必须仍是内核真实输出，不受胡说八道的 narration 影响
    assert findings["answer"] == "zeros: [-2, 2]"
    assert findings["steps"][1]["result"] == "[-2, 2]"
    # narration 本身确实存了下来（不是被丢弃），只是不影响权威字段
    assert "x=100" in findings["narration"]


@pytest.mark.asyncio
async def test_narration_skipped_when_kernel_could_not_solve():
    """内核不可解时不应该浪费一次 LLM 调用去"讲解"一个不存在的解。"""
    caller = _scripted_caller(
        plan_payload={
            "kernel": "sequence",
            "task": "nth_term",
            "params": {"terms": [1, 2, 4, 8]},  # 缺 n，nth_term 必然失败
            "restated_problem": "求第几项",
        },
        narration_text="不应该被调用到这里",
    )
    result = await solve_problem(
        config=SolveProblemConfig(),
        input_data=SolveProblemInput(problem_text="求第几项"),
        caller=caller,
    )
    assert result["status"] == "failed"
    assert result["findings"]["solvable"] is False
    assert result["findings"]["narration"] == ""


@pytest.mark.asyncio
async def test_plan_failure_short_circuits_before_any_kernel_call():
    """题意理解失败（未知内核）时，必须在 solve_dispatch 之前就短路返回，
    不能带着一个空/无效的 plan 硬跑下去。"""

    async def call(*, messages, system=None, max_tokens=800):
        return {"content": json.dumps({"kernel": "not_real", "task": "", "params": {}})}

    result = await solve_problem(
        config=SolveProblemConfig(),
        input_data=SolveProblemInput(problem_text="随便一道题"),
        caller=call,
    )
    assert result["status"] == "failed"
    assert len(result["decision_trail"]) == 1
    assert result["decision_trail"][0]["step"] == "plan_solve_task"


@pytest.mark.asyncio
async def test_no_caller_available_fails_gracefully_not_crash():
    """caller=None（未配置任何 provider）必须优雅失败，不是抛未捕获异常。"""
    result = await solve_problem(
        config=SolveProblemConfig(),
        input_data=SolveProblemInput(problem_text="随便一道题"),
        caller=None,
    )
    assert result["status"] == "failed"
