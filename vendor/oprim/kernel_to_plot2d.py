"""Convert kernel SolveResult to Plot2DData for 2D visualisation.

Pure deterministic kernel — no LLM calls.
Converts a SolveResult (function expression, conic, trig, etc.) to
Plot2DData that can be rendered by any plotting library.

Version: oprim v3.4.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from obase.sympy_runtime import SymPyRuntime
from oprim.types import Plot2DData, SolveResult

_runtime = SymPyRuntime()

# LLM/调用方可以请求任意 num_points——不设上限的话，采样点数本身就是一个
# 数值 DoS 面（S0 同一类风险，只是这次是"点数"而不是"组合数 n/k"）。
_MAX_NUM_POINTS = 500


@dataclass(frozen=True)
class Plot2DRequest:
    """Parameters for generating a 2D plot from a SolveResult."""

    expression: str  # f(x) or conic equation
    variable: str = "x"
    x_range: tuple[float, float] = (-10.0, 10.0)
    y_range: tuple[float, float] = (-10.0, 10.0)
    num_points: int = 200
    title: str = ""
    x_label: str = "x"
    y_label: str = "y"
    mark_zeros: bool = True  # annotate zero crossings
    mark_extrema: bool = False  # annotate extrema
    solve_result: SolveResult | None = None


def _sample_function(
    expr_str: str,
    var: str,
    x_range: tuple[float, float],
    num_points: int,
) -> tuple[list[float], list[float]]:
    """Sample f(x) over x_range at num_points.

    S0 加固：expr_str 是调用方（Visualize 模式下可能是 LLM）提供的字符串，
    加固前直接对它跑裸 sympy 解析，零 AST 校验、零 fork/timeout/内存
    上限——同 S0 修过的 solve_conic/derivative/trig/function 那一类真代码
    注入风险面。这里先用 SymPyRuntime.evaluate() 做一次 AST 校验+沙箱化
    解析（只解析一次，不是每个采样点都重新解析——重新解析会导致每次采样
    都 fork 一次进程，200 个点等于 200 次 fork，代价太大)，解析出的已验证
    表达式对象再拿去做实际的多点数值求值；这个求值循环本身也包一层
    run_isolated（fork+timeout+内存上限），防止病态表达式在 evalf() 阶段
    卡死或吃爆内存。

    注意：SymPyRuntime.evaluate() 对 AST 白名单拦截（SymPyRestrictedError）/
    超时（SymPyTimeoutError）/内存超限（SymPyMemoryError）是直接抛异常，
    不是包进 EvalResult(success=False)（同 solve_conic 等内核的既有调用
    约定一致，见 obase/sympy_runtime.py 里 `except (SymPyRuntimeError,
    SymPyTimeoutError): raise` 那段）——这里必须显式 catch，否则恶意/
    病态表达式会导致本函数抛未捕获异常，而不是优雅降级返回空数据。
    """
    try:
        parsed = _runtime.evaluate(expr_str, {var: var}, simplify_result=False)
    except Exception:
        return [], []
    if not parsed.success or parsed.value is None:
        return [], []

    expr = parsed.value
    capped_points = min(num_points, _MAX_NUM_POINTS)
    x_min, x_max = x_range
    step = (x_max - x_min) / max(capped_points - 1, 1)

    def _compute() -> tuple[list[float], list[float]]:
        import sympy as sp

        sym = sp.Symbol(var)
        xs: list[float] = []
        ys: list[float] = []
        for i in range(capped_points):
            xv = x_min + i * step
            try:
                val = float(expr.subs(sym, xv).evalf())
            except Exception:
                continue
            if math.isfinite(val):
                xs.append(xv)
                ys.append(val)
        return xs, ys

    try:
        return _runtime.run_isolated(_compute)
    except Exception:
        return [], []


def _find_zero_crossings(
    xs: list[float], ys: list[float]
) -> list[tuple[float, float, str]]:
    """Find approximate zero crossings by sign change."""
    annotations: list[tuple[float, float, str]] = []
    for i in range(len(xs) - 1):
        if ys[i] * ys[i + 1] < 0:
            # Linear interpolation
            x_zero = xs[i] - ys[i] * (xs[i + 1] - xs[i]) / (ys[i + 1] - ys[i])
            annotations.append((x_zero, 0.0, f"zero ≈ {x_zero:.3g}"))
    return annotations


def kernel_to_plot2d(request: Plot2DRequest) -> Plot2DData:
    """Convert a function expression (and optional SolveResult) to Plot2DData.

    Parameters
    ----------
    request : Plot2DRequest

    Returns
    -------
    Plot2DData
        Ready-to-render 2D plot data.
    """
    xs, ys = _sample_function(
        request.expression,
        request.variable,
        request.x_range,
        request.num_points,
    )

    annotations: list[tuple[float, float, str]] = []
    if request.mark_zeros and xs:
        annotations.extend(_find_zero_crossings(xs, ys))

    # If solve_result has an answer with zero info, also annotate
    if request.solve_result and request.solve_result.solvable:
        result_answer = request.solve_result.answer
        if "zeros:" in result_answer:
            # Already annotated via _find_zero_crossings
            pass

    title = request.title or f"y = {request.expression}"
    functions = {f"y = {request.expression}": request.expression}

    return Plot2DData(
        title=title,
        x_label=request.x_label,
        y_label=request.y_label,
        x_values=xs,
        y_values=ys,
        annotations=annotations,
        functions=functions,
        x_range=request.x_range,
        y_range=request.y_range,
    )


def solve_result_to_plot2d(
    result: SolveResult,
    expression: str,
    *,
    x_range: tuple[float, float] = (-10.0, 10.0),
    num_points: int = 200,
) -> Plot2DData:
    """Convenience wrapper: convert a SolveResult to Plot2DData."""
    return kernel_to_plot2d(
        Plot2DRequest(
            expression=expression,
            x_range=x_range,
            num_points=num_points,
            solve_result=result,
            mark_zeros=True,
        )
    )
