"""VZ-4 端到端验收：omodul.visualize_concept 全链路，渲染数据来自内核真实
输出，mermaid 诚实标注为 LLM 内容。
"""

from __future__ import annotations

import json

import pytest

from omodul.visualize_concept import (
    VisualizeConceptConfig,
    VisualizeConceptInput,
    visualize_concept,
)


def _scripted_caller(payload: dict):
    async def call(*, messages, system=None, max_tokens=800):
        return {"content": json.dumps(payload, ensure_ascii=False)}

    return call


@pytest.mark.asyncio
async def test_end_to_end_svg_plot_data_traces_to_real_kernel():
    caller = _scripted_caller(
        {
            "render_type": "svg_plot",
            "params": {"expression": "x**2 - 4", "variable": "x"},
            "restated_concept": "画出 y=x^2-4 的图像",
        }
    )
    result = await visualize_concept(
        config=VisualizeConceptConfig(),
        input_data=VisualizeConceptInput(concept_text="画出 y=x^2-4 的图像"),
        caller=caller,
    )
    assert result["status"] == "success"
    findings = result["findings"]
    assert findings["render_type"] == "svg_plot"
    assert "<svg" in findings["svg"]
    assert findings["data_source"] == "kernel_to_plot2d"
    trail_steps = [t["step"] for t in result["decision_trail"]]
    assert trail_steps == ["plan_visualize_task", "visualize_dispatch"]


@pytest.mark.asyncio
async def test_end_to_end_mermaid_is_honestly_labeled():
    caller = _scripted_caller(
        {
            "render_type": "mermaid",
            "params": {"diagram_source": "flowchart TD\nA[开始]-->B[结束]"},
            "restated_concept": "画个流程图",
        }
    )
    result = await visualize_concept(
        config=VisualizeConceptConfig(),
        input_data=VisualizeConceptInput(concept_text="画个流程图"),
        caller=caller,
    )
    assert result["status"] == "success"
    findings = result["findings"]
    assert findings["render_type"] == "mermaid"
    assert findings["data_source"] == "llm_authored"


@pytest.mark.asyncio
async def test_plan_failure_short_circuits_before_dispatch():
    async def call(*, messages, system=None, max_tokens=800):
        return {"content": json.dumps({"render_type": "not_real", "params": {}})}

    result = await visualize_concept(
        config=VisualizeConceptConfig(),
        input_data=VisualizeConceptInput(concept_text="随便一个概念"),
        caller=call,
    )
    assert result["status"] == "failed"
    assert len(result["decision_trail"]) == 1
    assert result["decision_trail"][0]["step"] == "plan_visualize_task"


@pytest.mark.asyncio
async def test_no_caller_available_fails_gracefully_not_crash():
    result = await visualize_concept(
        config=VisualizeConceptConfig(),
        input_data=VisualizeConceptInput(concept_text="随便一个概念"),
        caller=None,
    )
    assert result["status"] == "failed"
