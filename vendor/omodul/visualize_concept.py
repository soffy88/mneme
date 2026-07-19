"""omodul.visualize_concept —— W4 Visualize 模式：数学概念/数据 -> 渲染数据。

两段流水线（比 Solve 少一段——Visualize 没有"求解答案对错"这个维度，不需要
类似 narrate_solve_steps 的讲解层；restated_concept 已经足够让前端展示"系统
理解了什么"）：

1. plan_visualize_task（mneme-core 私有 oskill，LLM）：概念/数据描述 ->
   {render_type, params}，已校验 render_type 只能是 4 种真实支持的类型
   （svg_plot/three/chart/mermaid）。
2. visualize_dispatch（vendor/oskill，纯确定性除 mermaid 分支外）：产出
   实际渲染数据——svg_plot/three/chart 三种类型 100% 来自 S0 加固后的真实
   内核（kernel_to_plot2d/kernel_to_three/solve_sequence），mermaid 类型
   诚实标注为 LLM 直接撰写的声明式文本（data_source="llm_authored"，不
   伪装成内核数据）。

同 vendor/omodul/solve_problem.py 一致，走 omodul.base 的轻量 BaseConfig/
standard_return。_enabled_pillars = {"decision_trail"}：记录 LLM 选了哪个
渲染类型、内核是否成功产出数据，便于事后审计。
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel

from mneme_core.oskill.plan_visualize_task import plan_visualize_task
from omodul.base import BaseConfig, standard_return
from oskill.visualize_dispatch import visualize_dispatch


class VisualizeConceptConfig(BaseConfig):
    _omodul_name: ClassVar[str] = "visualize_concept"
    _omodul_version: ClassVar[str] = "0.1.0"
    _enabled_pillars: ClassVar[set] = {"decision_trail"}


class VisualizeConceptInput(BaseModel):
    concept_text: str


async def visualize_concept(
    config: VisualizeConceptConfig,
    input_data: VisualizeConceptInput,
    *,
    caller: Any,
) -> dict:
    """自然语言概念/数据描述 -> 真实渲染数据，标准 omodul 签名。

    失败不 raise，走 standard_return(status="failed")——概念理解失败/
    渲染数据产出失败都是正常的业务结果，不是需要 500 的系统异常。
    """
    trail: list[dict] = []

    try:
        plan = await plan_visualize_task(caller, concept_text=input_data.concept_text)
        trail.append(
            {
                "step": "plan_visualize_task",
                "render_type": plan.render_type,
                "error": plan.error,
            }
        )

        if plan.error:
            return standard_return(
                findings={"error": plan.error},
                status="failed",
                error=plan.error,
                trail=trail,
            )

        render = visualize_dispatch(plan.render_type, plan.params)
        trail.append(
            {
                "step": "visualize_dispatch",
                "render_type": plan.render_type,
                "success": render.get("success", False),
                "data_source": render.get("data_source", ""),
            }
        )

        findings = {
            "render_type": plan.render_type,
            "restated_concept": plan.restated_concept,
            **render,
        }

        return standard_return(
            findings=findings,
            status="success" if render.get("success") else "failed",
            error=render.get("error") if not render.get("success") else None,
            trail=trail,
        )
    except Exception as exc:
        trail.append({"event": "error", "message": str(exc)})
        return standard_return(
            findings=None, status="failed", error=str(exc), trail=trail
        )


__all__ = ["VisualizeConceptConfig", "VisualizeConceptInput", "visualize_concept"]
