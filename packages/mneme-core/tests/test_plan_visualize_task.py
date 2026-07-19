"""Tests for plan_visualize_task (W4 Visualize §3 — 题意理解层).

Same convention as test_plan_solve_task.py: scripted fake async LLMCaller,
zero provider dependency.
"""

from __future__ import annotations

import json

import pytest

from mneme_core.oskill.plan_visualize_task import plan_visualize_task


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
async def test_happy_path_svg_plot():
    llm = _caller(
        {
            "render_type": "svg_plot",
            "params": {"expression": "x**2-4", "variable": "x"},
            "restated_concept": "画出 y=x^2-4 的图像",
        }
    )
    plan = await plan_visualize_task(llm, concept_text="画出 y=x^2-4 的图像")
    assert plan.error == ""
    assert plan.render_type == "svg_plot"
    assert plan.params == {"expression": "x**2-4", "variable": "x"}


@pytest.mark.asyncio
async def test_unknown_render_type_is_rejected_not_guessed():
    llm = _caller(
        {
            "render_type": "matplotlib_3d",  # 不存在
            "params": {},
            "restated_concept": "x",
        }
    )
    plan = await plan_visualize_task(llm, concept_text="随便一个概念")
    assert plan.error != ""
    assert plan.render_type == ""


@pytest.mark.asyncio
async def test_mermaid_requires_diagram_source():
    llm = _caller(
        {
            "render_type": "mermaid",
            "params": {},
            "restated_concept": "画个流程图",
        }
    )
    plan = await plan_visualize_task(llm, concept_text="画个流程图")
    assert plan.error != ""


@pytest.mark.asyncio
async def test_mermaid_with_valid_diagram_source_passes():
    llm = _caller(
        {
            "render_type": "mermaid",
            "params": {"diagram_source": "flowchart TD\nA[开始]-->B[求解]"},
            "restated_concept": "解题流程图",
        }
    )
    plan = await plan_visualize_task(llm, concept_text="画个解题流程图")
    assert plan.error == ""
    assert plan.render_type == "mermaid"


@pytest.mark.asyncio
async def test_mermaid_suspicious_content_is_rejected():
    """防御性检查：mermaid diagram_source 含明显脚本注入字样时拒绝——
    mermaid.js 本身不执行任意 JS，但纵深防御多一层不亏。"""
    llm = _caller(
        {
            "render_type": "mermaid",
            "params": {"diagram_source": "flowchart TD\nA[<script>alert(1)</script>]"},
            "restated_concept": "x",
        }
    )
    plan = await plan_visualize_task(llm, concept_text="x")
    assert plan.error != ""


@pytest.mark.asyncio
async def test_llm_exception_returns_error_plan_not_raise():
    llm = _raising_caller()
    plan = await plan_visualize_task(llm, concept_text="随便一个概念")
    assert plan.error != ""
    assert plan.render_type == ""


@pytest.mark.asyncio
async def test_json_wrapped_in_markdown_fence_still_parses():
    payload = {
        "render_type": "chart",
        "params": {"mode": "function", "expression": "sin(x)"},
        "restated_concept": "画正弦函数图表",
    }
    llm = _caller("```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```")
    plan = await plan_visualize_task(llm, concept_text="画正弦函数图表")
    assert plan.error == ""
    assert plan.render_type == "chart"
