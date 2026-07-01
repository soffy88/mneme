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

from oprim.types import Plot2DData, SolveResult


@dataclass(frozen=True)
class Plot2DRequest:
    """Parameters for generating a 2D plot from a SolveResult."""

    expression: str                # f(x) or conic equation
    variable: str = "x"
    x_range: tuple[float, float] = (-10.0, 10.0)
    y_range: tuple[float, float] = (-10.0, 10.0)
    num_points: int = 200
    title: str = ""
    x_label: str = "x"
    y_label: str = "y"
    mark_zeros: bool = True         # annotate zero crossings
    mark_extrema: bool = False      # annotate extrema
    solve_result: SolveResult | None = None


def _safe_eval_at(expr_str: str, var: str, x_val: float) -> float | None:
    """Evaluate expression at a point; return None on error."""
    try:
        import sympy as sp
        sym = sp.Symbol(var)
        f = sp.sympify(expr_str)
        val = float(f.subs(sym, x_val).evalf())
        if math.isfinite(val):
            return val
        return None
    except Exception:
        return None


def _sample_function(
    expr_str: str,
    var: str,
    x_range: tuple[float, float],
    num_points: int,
) -> tuple[list[float], list[float]]:
    """Sample f(x) over x_range at num_points."""
    x_min, x_max = x_range
    xs: list[float] = []
    ys: list[float] = []
    step = (x_max - x_min) / max(num_points - 1, 1)
    for i in range(num_points):
        xv = x_min + i * step
        yv = _safe_eval_at(expr_str, var, xv)
        if yv is not None:
            xs.append(xv)
            ys.append(yv)
    return xs, ys


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
