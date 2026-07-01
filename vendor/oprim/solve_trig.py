"""Solve trigonometric equation problems using SymPy.

Pure deterministic kernel — no LLM calls.
Handles: solve trig equations, simplify trig expressions, evaluate at angles,
find period/amplitude, verify identities.

Version: oprim v3.4.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from obase.sympy_runtime import SymPyRuntime

from oprim.types import SolveResult, SolveStep


TaskType = Literal[
    "solve", "simplify", "evaluate", "period", "identity", "auto"
]


@dataclass(frozen=True)
class TrigSolveInput:
    """Input for a trigonometric problem."""

    expression: str
    variable: str = "x"
    task: TaskType = "auto"
    angle_degrees: float | None = None   # for "evaluate"
    rhs: str = "0"                        # RHS when task="solve" (expr = rhs)
    timeout: float = 5.0


def _deg_to_rad(deg: float) -> float:
    return deg * math.pi / 180.0


def solve_trig(inp: TrigSolveInput) -> SolveResult:
    """Solve a trigonometric problem deterministically.

    Parameters
    ----------
    inp : TrigSolveInput

    Returns
    -------
    SolveResult
    """
    steps: list[SolveStep] = []

    task = inp.task
    if task == "auto":
        if inp.angle_degrees is not None:
            task = "evaluate"
        else:
            task = "solve"

    try:
        import sympy as sp

        x = sp.Symbol(inp.variable)
        f = sp.sympify(inp.expression)

        steps.append(
            SolveStep(
                step_number=1,
                description="Parse trigonometric expression",
                expression=inp.expression,
                result=str(f),
            )
        )

        if task == "solve":
            rhs = sp.sympify(inp.rhs)
            eq = sp.Eq(f, rhs)
            solutions = sp.solve(eq, x)
            steps.append(
                SolveStep(
                    step_number=2,
                    description=f"Solve {inp.expression} = {inp.rhs}",
                    expression=str(eq),
                    result=str(solutions),
                )
            )
            answer = f"solutions: {solutions}"
            latex_str = sp.latex(eq)

        elif task == "simplify":
            simplified = sp.trigsimp(f)
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Apply trigonometric simplification",
                    expression=inp.expression,
                    result=str(simplified),
                )
            )
            answer = str(simplified)
            latex_str = sp.latex(simplified)

        elif task == "evaluate":
            if inp.angle_degrees is None:
                return SolveResult(
                    solvable=False,
                    answer="",
                    steps=steps,
                    error="evaluate task requires angle_degrees",
                )
            angle_rad = _deg_to_rad(inp.angle_degrees)
            val = f.subs(x, angle_rad)
            val_simplified = sp.trigsimp(sp.nsimplify(val, rational=False))
            val_float = float(val_simplified.evalf())
            steps.append(
                SolveStep(
                    step_number=2,
                    description=f"Evaluate at {inp.angle_degrees}°",
                    expression=f"x = {angle_rad:.6g} rad",
                    result=str(val_simplified),
                )
            )
            answer = f"f({inp.angle_degrees}°) = {val_simplified} ≈ {val_float:.6g}"
            latex_str = sp.latex(val_simplified)

        elif task == "period":
            period = sp.periodicity(f, x)
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Compute period",
                    expression=inp.expression,
                    result=str(period),
                )
            )
            answer = f"period = {period}"
            latex_str = sp.latex(period) if period else "aperiodic"

        elif task == "identity":
            simplified = sp.trigsimp(sp.expand_trig(f))
            is_zero = sp.simplify(simplified) == 0
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Verify identity (simplify LHS - RHS to 0)",
                    expression=inp.expression,
                    result=str(simplified),
                )
            )
            answer = f"identity verified: {is_zero}; simplified form: {simplified}"
            latex_str = sp.latex(simplified)

        else:
            return SolveResult(
                solvable=False,
                answer="",
                steps=steps,
                error=f"Unknown task: {task}",
                raw_expression=inp.expression,
            )

        return SolveResult(
            solvable=True,
            answer=answer,
            steps=steps,
            method="kernel",
            raw_expression=inp.expression,
            solution_latex=latex_str,
            confidence=1.0,
        )

    except Exception as exc:
        return SolveResult(
            solvable=False,
            answer="",
            steps=steps,
            error=str(exc),
            raw_expression=inp.expression,
        )
