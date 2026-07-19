"""omodul.solve_problem —— W4 Solve 模式：自然语言题目 -> 内核求解 -> 讲解。

标准三段：
1. plan_solve_task（mneme-core 私有 oskill，LLM）：题目 -> {kernel, task,
   params}，已校验 kernel/task 只能是 7 个真实内核里存在的值。
2. solve_dispatch（vendor/oskill，纯确定性）：调用对应内核，真实求解
   （S0 加固后 7 内核全经沙箱，本层不引入任何新绕过路径——只是构造内核
   自己的 Input dataclass 再调用其公开函数）。
3. narrate_solve_steps（mneme-core 私有 oskill，LLM）：内核真实 steps/
   answer -> 自然语言讲解（纯附加，findings.answer/findings.steps 原样
   来自内核，不经 LLM 二次处理——SV-2/SV-4 红线在这里落地）。

同 vendor/omodul/deep_solve_workflow.py 一致，走 omodul.base 的轻量
BaseConfig/standard_return（不是 book_compile.py 那套四支柱 Trail/
CostTracker——Solve 是活请求交互工具，不是可去重持久化的批量内容编译任务，
与 deep_solve_workflow 是更贴近的同类，不照搬 Book Engine 的重量级约定）。
_enabled_pillars = {"decision_trail"}：记录每一步的判断过程（LLM 选了哪个
内核/task、内核是否求解成功），便于事后审计；不启用 fingerprint/report/cost。
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel

from mneme_core.oskill.narrate_solve_steps import narrate_solve_steps
from mneme_core.oskill.plan_solve_task import plan_solve_task
from omodul.base import BaseConfig, standard_return
from oskill.solve_dispatch import solve_dispatch


class SolveProblemConfig(BaseConfig):
    _omodul_name: ClassVar[str] = "solve_problem"
    _omodul_version: ClassVar[str] = "0.1.0"
    _enabled_pillars: ClassVar[set] = {"decision_trail"}


class SolveProblemInput(BaseModel):
    problem_text: str


async def solve_problem(
    config: SolveProblemConfig,
    input_data: SolveProblemInput,
    *,
    caller: Any,
) -> dict:
    """自然语言题目 -> 内核真实求解 + LLM 讲解，标准 omodul 签名。

    失败不 raise，走 standard_return(status="failed")——题意理解失败/内核
    不可解都是正常的业务结果，不是需要 500 的系统异常。
    """
    trail: list[dict] = []

    try:
        plan = await plan_solve_task(caller, problem_text=input_data.problem_text)
        trail.append(
            {
                "step": "plan_solve_task",
                "kernel": plan.kernel,
                "task": plan.task,
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

        solve_result = solve_dispatch(plan.kernel, plan.task, plan.params)
        trail.append(
            {
                "step": "solve_dispatch",
                "kernel": plan.kernel,
                "task": plan.task,
                "solvable": solve_result.solvable,
            }
        )

        steps_dicts = [
            {
                "step_number": s.step_number,
                "description": s.description,
                "expression": s.expression,
                "result": s.result,
            }
            for s in solve_result.steps
        ]

        narration = ""
        if solve_result.solvable:
            narration = await narrate_solve_steps(
                caller,
                kernel=plan.kernel,
                task=plan.task,
                answer=solve_result.answer,
                steps=steps_dicts,
            )
        trail.append({"step": "narrate_solve_steps", "narrated": bool(narration)})

        return standard_return(
            findings={
                "kernel": plan.kernel,
                "task": plan.task,
                "restated_problem": plan.restated_problem,
                "solvable": solve_result.solvable,
                # answer/steps 原样来自内核，narration 不得覆盖（SV-2/SV-4）
                "answer": solve_result.answer,
                "steps": steps_dicts,
                "error": solve_result.error,
                "narration": narration,
            },
            status="success" if solve_result.solvable else "failed",
            error=solve_result.error if not solve_result.solvable else None,
            trail=trail,
        )
    except Exception as exc:
        trail.append({"event": "error", "message": str(exc)})
        return standard_return(
            findings=None, status="failed", error=str(exc), trail=trail
        )


__all__ = ["SolveProblemConfig", "SolveProblemInput", "solve_problem"]
