"""Convert kernel SolveResult to Three3DData for 3D visualisation.

Pure deterministic kernel — no LLM calls.
Samples a 2-variable function z=f(x,y) or a parametric surface and
produces Three3DData for rendering.

Version: oprim v3.4.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from obase.sympy_runtime import SymPyRuntime
from oprim.types import Three3DData, SolveResult

_runtime = SymPyRuntime()

# grid_points² 次求值——比 2D 的点数更敏感（50 就是 2500 次），同样需要
# 上限防数值 DoS。
_MAX_GRID_POINTS = 40


@dataclass(frozen=True)
class Plot3DRequest:
    """Parameters for generating 3D data from an expression."""

    expression: str  # z = f(x, y) expression string
    x_var: str = "x"
    y_var: str = "y"
    x_range: tuple[float, float] = (-5.0, 5.0)
    y_range: tuple[float, float] = (-5.0, 5.0)
    grid_points: int = 20  # points per axis (grid_points² total)
    title: str = ""
    x_label: str = "x"
    y_label: str = "y"
    z_label: str = "z"
    solve_result: SolveResult | None = None


def kernel_to_three(request: Plot3DRequest) -> Three3DData:
    """Convert a 2-variable expression to Three3DData (surface mesh).

    Samples z = f(x, y) on a regular grid and returns all (x, y, z) triples
    as flat lists (suitable for Three.js BufferGeometry or similar).

    S0 加固：request.expression 是调用方（Visualize 模式下可能是 LLM）提供
    的字符串，加固前直接对它跑裸 sympy 解析——同 kernel_to_plot2d 的
    _sample_function 一样，先用 SymPyRuntime.evaluate() 做一次 AST 校验+
    沙箱化解析（只解析一次，不是 grid_points² 次都重新解析），已验证的
    表达式对象再拿去做网格求值，整个求值循环包一层 run_isolated
    （fork+timeout+内存上限）。grid_points 额外做上限裁剪（平方增长，比
    2D 的点数更敏感）。

    Parameters
    ----------
    request : Plot3DRequest

    Returns
    -------
    Three3DData
        Flat x_values / y_values / z_values lists (grid_points² entries each).
    """
    x_min, x_max = request.x_range
    y_min, y_max = request.y_range
    n = min(request.grid_points, _MAX_GRID_POINTS)

    # SymPyRuntime.evaluate() 对 AST 拦截/超时/内存超限是直接抛异常，不是
    # success=False（同 kernel_to_plot2d._sample_function 的注释），必须
    # 显式 catch，否则恶意/病态表达式会让本函数抛未捕获异常。
    try:
        parsed = _runtime.evaluate(
            request.expression,
            {request.x_var: request.x_var, request.y_var: request.y_var},
            simplify_result=False,
        )
    except Exception:
        parsed = None

    if parsed is None or not parsed.success or parsed.value is None:
        xs, ys, zs = [], [], []
    else:
        expr = parsed.value
        x_step = (x_max - x_min) / max(n - 1, 1)
        y_step = (y_max - y_min) / max(n - 1, 1)

        def _compute() -> tuple[list[float], list[float], list[float]]:
            import sympy as sp

            sx = sp.Symbol(request.x_var)
            sy = sp.Symbol(request.y_var)
            xs_: list[float] = []
            ys_: list[float] = []
            zs_: list[float] = []
            for i in range(n):
                xv = x_min + i * x_step
                for j in range(n):
                    yv = y_min + j * y_step
                    try:
                        zv = float(expr.subs({sx: xv, sy: yv}).evalf())
                    except Exception:
                        continue
                    if math.isfinite(zv):
                        xs_.append(xv)
                        ys_.append(yv)
                        zs_.append(zv)
            return xs_, ys_, zs_

        try:
            xs, ys, zs = _runtime.run_isolated(_compute)
        except Exception:
            xs, ys, zs = [], [], []

    z_min = min(zs) if zs else -10.0
    z_max = max(zs) if zs else 10.0

    title = request.title or f"z = {request.expression}"

    return Three3DData(
        title=title,
        x_label=request.x_label,
        y_label=request.y_label,
        z_label=request.z_label,
        x_values=xs,
        y_values=ys,
        z_values=zs,
        surface_func=request.expression,
        x_range=request.x_range,
        y_range=request.y_range,
        z_range=(z_min, z_max),
    )


def solve_result_to_three(
    result: SolveResult,
    expression: str,
    *,
    x_range: tuple[float, float] = (-5.0, 5.0),
    y_range: tuple[float, float] = (-5.0, 5.0),
    grid_points: int = 20,
) -> Three3DData:
    """Convenience wrapper: convert a SolveResult to Three3DData."""
    return kernel_to_three(
        Plot3DRequest(
            expression=expression,
            x_range=x_range,
            y_range=y_range,
            grid_points=grid_points,
            solve_result=result,
        )
    )
