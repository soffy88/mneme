"""Solve derivative problems using SymPy.

Pure deterministic kernel — no LLM calls.
Handles: compute derivative (any order), critical points, extrema
classification, inflection points, tangent line.

Version: oprim v3.4.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from obase.sympy_runtime import SymPyRuntime

from oprim.types import SolveResult, SolveStep


TaskType = Literal[
    "derivative", "critical_points", "extrema", "inflection",
    "tangent_line", "auto"
]


@dataclass(frozen=True)
class DerivativeSolveInput:
    """Input for a derivative problem."""

    expression: str
    variable: str = "x"
    order: int = 1
    task: TaskType = "auto"
    point: float | None = None   # for "tangent_line"
    timeout: float = 5.0


def solve_derivative(inp: DerivativeSolveInput) -> SolveResult:
    """Solve a derivative problem deterministically.

    Depending on inp.task:
    - "derivative": compute d^n f/dx^n
    - "critical_points": find where f'(x) = 0
    - "extrema": classify critical points as min/max/saddle
    - "inflection": find inflection points (f''(x) = 0 with sign change)
    - "tangent_line": equation of tangent at inp.point
    - "auto": derivative if no point, tangent_line if point given

    Parameters
    ----------
    inp : DerivativeSolveInput

    Returns
    -------
    SolveResult
    """
    steps: list[SolveStep] = []

    task = inp.task
    if task == "auto":
        if inp.point is not None:
            task = "tangent_line"
        else:
            task = "derivative"

    try:
        import sympy as sp
        x = sp.Symbol(inp.variable)
        f = sp.sympify(inp.expression)

        steps.append(
            SolveStep(
                step_number=1,
                description="Parse expression",
                expression=inp.expression,
                result=str(f),
            )
        )

        if task == "derivative":
            df = sp.diff(f, x, inp.order)
            df_simplified = sp.simplify(df)
            steps.append(
                SolveStep(
                    step_number=2,
                    description=f"Compute order-{inp.order} derivative",
                    expression=f"d^{inp.order}/d{inp.variable}^{inp.order}({inp.expression})",
                    result=str(df_simplified),
                )
            )
            answer = str(df_simplified)
            latex_str = sp.latex(df_simplified)

        elif task == "critical_points":
            df = sp.diff(f, x)
            critical = sp.solve(df, x)
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Compute first derivative",
                    expression=f"f'(x) = {df}",
                    result=str(sp.simplify(df)),
                )
            )
            steps.append(
                SolveStep(
                    step_number=3,
                    description="Solve f'(x) = 0",
                    expression=f"solve({sp.simplify(df)}, {inp.variable})",
                    result=str(critical),
                )
            )
            answer = f"critical points: {critical}"
            latex_str = sp.latex(sp.simplify(df)) + " = 0"

        elif task == "extrema":
            df = sp.diff(f, x)
            df2 = sp.diff(f, x, 2)
            critical = sp.solve(df, x)
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Find critical points",
                    expression=f"f'(x) = {sp.simplify(df)}",
                    result=str(critical),
                )
            )
            classifications = []
            for cp in critical:
                try:
                    val2 = df2.subs(x, cp)
                    val2_n = float(val2.evalf())
                    if val2_n > 0:
                        cls = "local_min"
                    elif val2_n < 0:
                        cls = "local_max"
                    else:
                        cls = "saddle_or_inflection"
                    f_val = float(f.subs(x, cp).evalf())
                    classifications.append(f"x={cp}: {cls} (f={f_val:.4g}, f''={val2_n:.4g})")
                except Exception:
                    classifications.append(f"x={cp}: classification failed")
            steps.append(
                SolveStep(
                    step_number=3,
                    description="Classify via second derivative test",
                    expression=f"f''(x) = {sp.simplify(df2)}",
                    result="; ".join(classifications),
                )
            )
            answer = "; ".join(classifications) if classifications else "no critical points"
            latex_str = sp.latex(sp.simplify(df2))

        elif task == "inflection":
            df2 = sp.diff(f, x, 2)
            infl = sp.solve(df2, x)
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Compute second derivative",
                    expression=f"f''(x) = {sp.simplify(df2)}",
                    result=str(sp.simplify(df2)),
                )
            )
            steps.append(
                SolveStep(
                    step_number=3,
                    description="Solve f''(x) = 0",
                    expression=f"solve({sp.simplify(df2)}, {inp.variable})",
                    result=str(infl),
                )
            )
            answer = f"inflection points: {infl}"
            latex_str = sp.latex(sp.simplify(df2)) + " = 0"

        elif task == "tangent_line":
            if inp.point is None:
                return SolveResult(
                    solvable=False,
                    answer="",
                    steps=steps,
                    error="tangent_line task requires inp.point",
                    raw_expression=inp.expression,
                )
            p = inp.point
            df = sp.diff(f, x)
            slope = float(df.subs(x, p).evalf())
            f_at_p = float(f.subs(x, p).evalf())
            # y - f(p) = slope*(x - p)  =>  y = slope*x + (f_at_p - slope*p)
            intercept = f_at_p - slope * p
            tangent = f"y = {slope:.4g}·{inp.variable} + {intercept:.4g}"
            steps.append(
                SolveStep(
                    step_number=2,
                    description=f"Compute slope at x={p}",
                    expression=f"f'({p}) = {slope:.4g}",
                    result=str(slope),
                )
            )
            steps.append(
                SolveStep(
                    step_number=3,
                    description="Write tangent line equation",
                    expression=tangent,
                    result=tangent,
                )
            )
            answer = tangent
            latex_str = f"y = {slope:.4g}x + {intercept:.4g}"

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
