"""Convert kernel SolveResult to Three3DData for 3D visualisation.

Pure deterministic kernel — no LLM calls.
Samples a 2-variable function z=f(x,y) or a parametric surface and
produces Three3DData for rendering.

Version: oprim v3.4.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from oprim.types import Three3DData, SolveResult


@dataclass(frozen=True)
class Plot3DRequest:
    """Parameters for generating 3D data from an expression."""

    expression: str               # z = f(x, y) expression string
    x_var: str = "x"
    y_var: str = "y"
    x_range: tuple[float, float] = (-5.0, 5.0)
    y_range: tuple[float, float] = (-5.0, 5.0)
    grid_points: int = 20         # points per axis (grid_points² total)
    title: str = ""
    x_label: str = "x"
    y_label: str = "y"
    z_label: str = "z"
    solve_result: SolveResult | None = None


def _safe_eval_z(expr_str: str, x_var: str, y_var: str, xv: float, yv: float) -> float | None:
    """Evaluate z=f(x,y) at a point; return None on error."""
    try:
        import sympy as sp
        sx = sp.Symbol(x_var)
        sy = sp.Symbol(y_var)
        f = sp.sympify(expr_str)
        val = float(f.subs({sx: xv, sy: yv}).evalf())
        if math.isfinite(val):
            return val
        return None
    except Exception:
        return None


def kernel_to_three(request: Plot3DRequest) -> Three3DData:
    """Convert a 2-variable expression to Three3DData (surface mesh).

    Samples z = f(x, y) on a regular grid and returns all (x, y, z) triples
    as flat lists (suitable for Three.js BufferGeometry or similar).

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
    n = request.grid_points

    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []

    x_step = (x_max - x_min) / max(n - 1, 1)
    y_step = (y_max - y_min) / max(n - 1, 1)

    for i in range(n):
        xv = x_min + i * x_step
        for j in range(n):
            yv = y_min + j * y_step
            zv = _safe_eval_z(request.expression, request.x_var, request.y_var, xv, yv)
            if zv is not None:
                xs.append(xv)
                ys.append(yv)
                zs.append(zv)

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
