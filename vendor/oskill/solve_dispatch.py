"""solve_dispatch —— Solve 模式内核调度层（W4 §2）。

给定结构化 SolveTaskPlan 数据（kernel/task/params），调用对应的
oprim.solve_* 内核（S0 加固后 7 个内核全部经沙箱），返回内核的真实
SolveResult——不经任何 LLM 二次处理（SV-2/SV-4 红线在这里落地：内核输出
是唯一的求解真源）。

组合 ≥2 oprim 形态：(1) kernel 名到内核模块的路由；(2) 对应内核 Input
dataclass 的构造 + 参数类型防御性转换（LLM 产出的 params 是弱类型 JSON，
不能直接假设类型对，转换失败要优雅降级成 solvable=False，不能让整条链路
因为一个字段类型不对而抛未捕获异常）。

SV-3（不得引入新绕过路径）：本层每个分支只是构造内核自己的 Input
dataclass、调用其公开函数——不直接 eval 任何字符串、不绕开内核内部已经
接入的沙箱（S0 加固后 conic/derivative/trig/function 的表达式参数会在
内核内部经 SymPyRuntime 的 AST 白名单校验，geometry3d/probability/sequence
的数值参数会在内核内部经 run_isolated 的 fork+timeout+内存上限）。

FC-6：无 Mneme 专属假设（不涉及 KC/textbook/student 概念，只是"选内核+
调用"这个通用调度逻辑），留在 vendor/oskill（3O 共享层），不进 mneme-core
私有——但读取 mneme-core 的 SOLVE_KERNEL_TASKS 作为 kernel/task 合法性的
单一权威来源，不在本文件里另建一份重复的合法值清单。
"""

from __future__ import annotations

from typing import Any

from mneme_core.oprim.models import SOLVE_KERNEL_TASKS
from oprim.types import SolveResult


def _as_float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_int_or_none(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_point_or_none(v: Any) -> tuple[float, float, float] | None:
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        return None
    try:
        return (float(v[0]), float(v[1]), float(v[2]))
    except (TypeError, ValueError):
        return None


def _as_float_list_or_none(v: Any) -> list[float] | None:
    if not isinstance(v, (list, tuple)):
        return None
    try:
        return [float(x) for x in v]
    except (TypeError, ValueError):
        return None


def solve_dispatch(kernel: str, task: str, params: dict[str, Any]) -> SolveResult:
    """kernel/task/params -> 真实内核 SolveResult。

    kernel/task 不合法、必需参数缺失/类型不对 -> solvable=False + error，
    绝不抛未捕获异常给调用方（同所有 solve_* 内核自身"失败不 raise"的约定）。
    """
    if kernel not in SOLVE_KERNEL_TASKS:
        return SolveResult(
            solvable=False, answer="", steps=[], error=f"Unknown kernel: {kernel!r}"
        )
    valid_tasks = SOLVE_KERNEL_TASKS[kernel]
    if valid_tasks and task not in valid_tasks:
        return SolveResult(
            solvable=False,
            answer="",
            steps=[],
            error=f"Unknown task {task!r} for kernel {kernel!r}",
        )

    try:
        if kernel == "function":
            from oprim.solve_function import FunctionSolveInput, solve_function

            return solve_function(
                FunctionSolveInput(
                    expression=str(params.get("expression", "")),
                    variable=str(params.get("variable", "x")),
                    task=task,  # type: ignore[arg-type]
                    point=_as_float_or_none(params.get("point")),
                    g_expression=params.get("g_expression") or None,
                )
            )
        elif kernel == "conic":
            from oprim.solve_conic import solve_conic

            return solve_conic(str(params.get("expression", "")))
        elif kernel == "derivative":
            from oprim.solve_derivative import DerivativeSolveInput, solve_derivative

            return solve_derivative(
                DerivativeSolveInput(
                    expression=str(params.get("expression", "")),
                    variable=str(params.get("variable", "x")),
                    order=_as_int_or_none(params.get("order")) or 1,
                    task=task,  # type: ignore[arg-type]
                    point=_as_float_or_none(params.get("point")),
                )
            )
        elif kernel == "trig":
            from oprim.solve_trig import TrigSolveInput, solve_trig

            return solve_trig(
                TrigSolveInput(
                    expression=str(params.get("expression", "")),
                    variable=str(params.get("variable", "x")),
                    task=task,  # type: ignore[arg-type]
                    angle_degrees=_as_float_or_none(params.get("angle_degrees")),
                    rhs=str(params.get("rhs", "0")),
                )
            )
        elif kernel == "sequence":
            from oprim.solve_sequence import SequenceSolveInput, solve_sequence

            terms = _as_float_list_or_none(params.get("terms"))
            if terms is None:
                return SolveResult(
                    solvable=False,
                    answer="",
                    steps=[],
                    error="sequence 内核需要 terms（数字列表）",
                )
            return solve_sequence(
                SequenceSolveInput(
                    terms=terms,
                    n=_as_int_or_none(params.get("n")),
                    count=_as_int_or_none(params.get("count")),
                    task=task,  # type: ignore[arg-type]
                )
            )
        elif kernel == "geometry3d":
            from oprim.solve_geometry3d import Geometry3DInput, solve_geometry3d

            return solve_geometry3d(
                Geometry3DInput(
                    task=task,  # type: ignore[arg-type]
                    p1=_as_point_or_none(params.get("p1")),
                    p2=_as_point_or_none(params.get("p2")),
                    radius=_as_float_or_none(params.get("radius")),
                    height=_as_float_or_none(params.get("height")),
                    normal1=_as_point_or_none(params.get("normal1")),
                    normal2=_as_point_or_none(params.get("normal2")),
                )
            )
        elif kernel == "probability":
            from oprim.solve_probability import (
                ProbabilitySolveInput,
                solve_probability,
            )

            return solve_probability(
                ProbabilitySolveInput(
                    task=task,  # type: ignore[arg-type]
                    n=_as_int_or_none(params.get("n")),
                    k=_as_int_or_none(params.get("k")),
                    p_a=_as_float_or_none(params.get("p_a")),
                    p_b=_as_float_or_none(params.get("p_b")),
                    p_a_given_b=_as_float_or_none(params.get("p_a_given_b")),
                    p_b_given_a=_as_float_or_none(params.get("p_b_given_a")),
                    p_success=_as_float_or_none(params.get("p_success")),
                    values=_as_float_list_or_none(params.get("values")),
                    probabilities=_as_float_list_or_none(params.get("probabilities")),
                )
            )
        else:
            return SolveResult(
                solvable=False,
                answer="",
                steps=[],
                error=f"Unhandled kernel: {kernel!r}",
            )
    except (TypeError, ValueError) as exc:
        return SolveResult(
            solvable=False, answer="", steps=[], error=f"Invalid params: {exc}"
        )


__all__ = ["solve_dispatch"]
