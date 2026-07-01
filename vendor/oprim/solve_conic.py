"""Solve conic section problems using SymPy.

Pure deterministic kernel — no LLM calls.
Identifies conic type (circle/ellipse/parabola/hyperbola) and extracts
standard parameters from a general 2nd-degree equation.

Version: oprim v3.4.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from obase.sympy_runtime import SymPyRuntime, SymPyRuntimeError

from oprim.types import SolveResult, SolveStep


ConicType = Literal["circle", "ellipse", "parabola", "hyperbola", "degenerate", "unknown"]


@dataclass(frozen=True)
class ConicParams:
    """Extracted standard parameters for a conic section."""

    conic_type: ConicType
    center: tuple[float, float] | None = None
    radii: tuple[float, float] | None = None  # (a, b) semi-axes
    focus: tuple[float, float] | None = None
    eccentricity: float | None = None
    discriminant: float | None = None
    standard_form: str = ""


def _classify_by_discriminant(A: float, B: float, C: float) -> ConicType:
    """Classify Ax^2 + Bxy + Cy^2 + ... by discriminant B^2 - 4AC."""
    disc = B * B - 4 * A * C
    if abs(disc) < 1e-10:
        return "parabola"
    elif disc < 0:
        if abs(A - C) < 1e-10 and abs(B) < 1e-10:
            return "circle"
        return "ellipse"
    else:
        return "hyperbola"


def _extract_circle_params(coeffs: dict) -> ConicParams:
    """Extract circle centre and radius from Ax^2 + Ay^2 + Dx + Ey + F = 0."""
    A = coeffs.get("x2", 0.0)
    D = coeffs.get("x", 0.0)
    E = coeffs.get("y", 0.0)
    F = coeffs.get("c", 0.0)
    if abs(A) < 1e-12:
        return ConicParams(conic_type="degenerate")
    h = -D / (2 * A)
    k = -E / (2 * A)
    r2 = h * h + k * k - F / A
    if r2 < 0:
        return ConicParams(conic_type="degenerate")
    r = math.sqrt(r2)
    return ConicParams(
        conic_type="circle",
        center=(h, k),
        radii=(r, r),
        eccentricity=0.0,
        standard_form=f"(x - {h:.4g})^2 + (y - {k:.4g})^2 = {r:.4g}^2",
    )


def _extract_ellipse_params(coeffs: dict) -> ConicParams:
    """Extract ellipse parameters (simplified, no rotation)."""
    A = coeffs.get("x2", 0.0)
    C = coeffs.get("y2", 0.0)
    D = coeffs.get("x", 0.0)
    E = coeffs.get("y", 0.0)
    F = coeffs.get("c", 0.0)
    if abs(A) < 1e-12 or abs(C) < 1e-12:
        return ConicParams(conic_type="degenerate")
    h = -D / (2 * A)
    k = -E / (2 * C)
    rhs = h * h * A + k * k * C - F
    if rhs <= 0:
        return ConicParams(conic_type="degenerate")
    a2 = rhs / A
    b2 = rhs / C
    a = math.sqrt(a2)
    b = math.sqrt(b2)
    if a >= b:
        e = math.sqrt(1 - b2 / a2)
    else:
        e = math.sqrt(1 - a2 / b2)
    return ConicParams(
        conic_type="ellipse",
        center=(h, k),
        radii=(a, b),
        eccentricity=e,
        standard_form=f"(x - {h:.4g})^2/{a:.4g}^2 + (y - {k:.4g})^2/{b:.4g}^2 = 1",
    )


def _extract_hyperbola_params(coeffs: dict) -> ConicParams:
    """Extract hyperbola parameters (simplified, no rotation)."""
    A = coeffs.get("x2", 0.0)
    C = coeffs.get("y2", 0.0)
    D = coeffs.get("x", 0.0)
    E = coeffs.get("y", 0.0)
    F = coeffs.get("c", 0.0)
    if abs(A) < 1e-12 or abs(C) < 1e-12:
        return ConicParams(conic_type="degenerate")
    h = -D / (2 * A)
    k = -E / (2 * C)
    rhs = h * h * A + k * k * C - F
    if abs(rhs) < 1e-12:
        return ConicParams(conic_type="degenerate")
    a2 = abs(rhs / A)
    b2 = abs(rhs / C)
    a = math.sqrt(a2)
    b = math.sqrt(b2)
    e = math.sqrt(1 + b2 / a2)
    return ConicParams(
        conic_type="hyperbola",
        center=(h, k),
        radii=(a, b),
        eccentricity=e,
        standard_form=f"(x - {h:.4g})^2/{a:.4g}^2 - (y - {k:.4g})^2/{b:.4g}^2 = 1",
    )


def _parse_coefficients(expr_str: str) -> dict[str, float]:
    """Extract polynomial coefficients from expression string via SymPy."""
    try:
        import sympy as sp
        x, y = sp.symbols("x y")
        expr = sp.sympify(expr_str)
        poly = sp.Poly(sp.expand(expr), x, y)
        monoms = poly.as_dict()
        result: dict[str, float] = {}
        for (px, py), coef in monoms.items():
            if px == 2 and py == 0:
                result["x2"] = float(coef)
            elif px == 0 and py == 2:
                result["y2"] = float(coef)
            elif px == 1 and py == 1:
                result["xy"] = float(coef)
            elif px == 1 and py == 0:
                result["x"] = float(coef)
            elif px == 0 and py == 1:
                result["y"] = float(coef)
            elif px == 0 and py == 0:
                result["c"] = float(coef)
        return result
    except Exception:
        return {}


def solve_conic(expression: str, *, timeout: float = 5.0) -> SolveResult:
    """Identify and solve a conic section problem.

    Accepts the left-hand side of an equation Ax^2 + Bxy + Cy^2 + Dx + Ey + F = 0,
    or an equality like "x^2/4 + y^2/9 = 1" (subtract RHS from LHS).

    Parameters
    ----------
    expression : str
        Conic equation or LHS expression.
    timeout : float
        SymPy evaluation timeout in seconds.

    Returns
    -------
    SolveResult
        solvable=True on success with answer = conic type.
        steps contains classification + parameter extraction.
    """
    steps: list[SolveStep] = []

    try:
        import sympy as sp

        # Normalise: handle "lhs = rhs" format
        if "=" in expression:
            lhs_str, rhs_str = expression.split("=", 1)
            expr_str = f"({lhs_str.strip()}) - ({rhs_str.strip()})"
        else:
            expr_str = expression.strip()

        steps.append(
            SolveStep(
                step_number=1,
                description="Normalise to standard form LHS = 0",
                expression=expr_str,
                result=expr_str,
            )
        )

        coeffs = _parse_coefficients(expr_str)
        if not coeffs:
            return SolveResult(
                solvable=False,
                answer="",
                steps=steps,
                error="Failed to parse expression coefficients",
            )

        A = coeffs.get("x2", 0.0)
        B = coeffs.get("xy", 0.0)
        C = coeffs.get("y2", 0.0)
        disc = B * B - 4 * A * C

        steps.append(
            SolveStep(
                step_number=2,
                description="Compute discriminant B²-4AC",
                expression=f"B²-4AC = {B}²-4·{A}·{C}",
                result=f"{disc:.6g}",
            )
        )

        conic_type = _classify_by_discriminant(A, B, C)

        steps.append(
            SolveStep(
                step_number=3,
                description="Classify conic type",
                expression=f"discriminant = {disc:.6g}",
                result=conic_type,
            )
        )

        # Extract parameters (only for axis-aligned conics without xy term)
        params: ConicParams
        if abs(B) > 1e-10:
            params = ConicParams(
                conic_type=conic_type,
                discriminant=disc,
                standard_form="(rotated conic — reduction required)",
            )
        elif conic_type == "circle":
            params = _extract_circle_params(coeffs)
        elif conic_type == "ellipse":
            params = _extract_ellipse_params(coeffs)
        elif conic_type == "hyperbola":
            params = _extract_hyperbola_params(coeffs)
        else:
            params = ConicParams(conic_type=conic_type, discriminant=disc)

        steps.append(
            SolveStep(
                step_number=4,
                description="Extract standard parameters",
                expression=params.standard_form,
                result=(
                    f"center={params.center}, "
                    f"radii={params.radii}, "
                    f"e={params.eccentricity}"
                ) if params.center else params.standard_form,
            )
        )

        import sympy as sp
        x_sym, y_sym = sp.symbols("x y")
        expr_sym = sp.sympify(expr_str)
        latex_str = sp.latex(expr_sym) + " = 0"

        answer_parts = [conic_type]
        if params.center:
            answer_parts.append(f"center={params.center}")
        if params.radii:
            answer_parts.append(f"a={params.radii[0]:.4g}, b={params.radii[1]:.4g}")
        if params.eccentricity is not None:
            answer_parts.append(f"e={params.eccentricity:.4g}")

        return SolveResult(
            solvable=True,
            answer="; ".join(answer_parts),
            steps=steps,
            method="kernel",
            raw_expression=expression,
            solution_latex=latex_str,
            confidence=1.0,
        )

    except Exception as exc:
        return SolveResult(
            solvable=False,
            answer="",
            steps=steps,
            error=str(exc),
            raw_expression=expression,
        )
