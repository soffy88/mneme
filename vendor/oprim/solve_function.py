"""Solve function problems using SymPy.

Pure deterministic kernel — no LLM calls.
Handles: find zeros, evaluate at point, domain analysis, range hints,
monotonicity, parity, and composition.

Version: oprim v3.4.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from obase.sympy_runtime import SymPyRuntime

from oprim.types import SolveResult, SolveStep


TaskType = Literal[
    "zeros",
    "evaluate",
    "domain",
    "monotonicity",
    "parity",
    "compose",
    "inverse",
    "simplify",
    "auto",
]


@dataclass(frozen=True)
class FunctionSolveInput:
    """Input specification for a function problem."""

    expression: str  # f(x) expression, e.g. "x**2 - 4"
    variable: str = "x"
    task: TaskType = "auto"
    point: float | None = None  # for "evaluate"
    g_expression: str | None = None  # for "compose"
    timeout: float = 5.0


def _find_zeros(
    expr_str: str, var: str, rt: SymPyRuntime, timeout: float
) -> tuple[str, str]:
    result = rt.solve_equation(expr_str, var, timeout=timeout)
    if result.success:
        return result.result_str, f"solve({expr_str}, {var})"
    return "could not solve", expr_str


def _evaluate_at(
    expr_str: str, var: str, point: float, rt: SymPyRuntime, timeout: float
) -> tuple[str, str]:
    result = rt.evaluate(f"({expr_str}).subs({var}, {point})", timeout=timeout)
    if result.success:
        return result.result_str, f"f({point})"
    # Fallback: use namespace substitution
    result2 = rt.evaluate(expr_str, {var: point}, timeout=timeout)
    if result2.success:
        return result2.result_str, f"f({point})"
    return "evaluation failed", expr_str


def _check_parity(
    expr_str: str, var: str, rt: SymPyRuntime, timeout: float
) -> tuple[str, str]:
    """Check if function is even, odd, or neither."""
    try:
        import sympy as sp

        x = sp.Symbol(var)
        parsed = rt.evaluate(
            expr_str, {var: var}, timeout=timeout, simplify_result=False
        )
        if not parsed.success or parsed.value is None:
            return "unknown", parsed.error or "parse failed"
        f = parsed.value
        f_neg = f.subs(x, -x)
        diff_even = sp.simplify(f_neg - f)
        diff_odd = sp.simplify(f_neg + f)
        if diff_even == 0:
            return "even", f"f(-x) - f(x) = 0"
        elif diff_odd == 0:
            return "odd", f"f(-x) + f(x) = 0"
        else:
            return "neither", f"f(-x)={f_neg}"
    except Exception as e:
        return "unknown", str(e)


def _simplify_expr(expr_str: str, rt: SymPyRuntime, timeout: float) -> tuple[str, str]:
    result = rt.simplify_expr(expr_str, timeout=timeout)
    if result.success:
        return result.result_str, "simplify"
    return expr_str, "no simplification"


def solve_function(inp: FunctionSolveInput) -> SolveResult:
    """Solve a function problem deterministically using SymPy.

    Parameters
    ----------
    inp : FunctionSolveInput
        Problem specification.

    Returns
    -------
    SolveResult
        solvable=True on success, steps contain intermediate work.
    """
    rt = SymPyRuntime()
    steps: list[SolveStep] = []

    task = inp.task
    if task == "auto":
        if inp.point is not None:
            task = "evaluate"
        elif inp.g_expression:
            task = "compose"
        else:
            task = "zeros"

    try:
        steps.append(
            SolveStep(
                step_number=1,
                description="Parse expression",
                expression=inp.expression,
                result=inp.expression,
            )
        )

        if task == "evaluate" and inp.point is not None:
            val, formula = _evaluate_at(
                inp.expression, inp.variable, inp.point, rt, inp.timeout
            )
            steps.append(
                SolveStep(
                    step_number=2,
                    description=f"Evaluate f({inp.point})",
                    expression=formula,
                    result=val,
                )
            )
            answer = f"f({inp.point}) = {val}"

        elif task == "zeros":
            zeros_str, formula = _find_zeros(
                inp.expression, inp.variable, rt, inp.timeout
            )
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Find zeros (solve f(x)=0)",
                    expression=formula,
                    result=zeros_str,
                )
            )
            answer = f"zeros: {zeros_str}"

        elif task == "parity":
            parity, detail = _check_parity(
                inp.expression, inp.variable, rt, inp.timeout
            )
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Check parity",
                    expression=detail,
                    result=parity,
                )
            )
            answer = f"parity: {parity}"

        elif task == "simplify":
            simplified, detail = _simplify_expr(inp.expression, rt, inp.timeout)
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Simplify expression",
                    expression=inp.expression,
                    result=simplified,
                )
            )
            answer = simplified

        elif task == "compose" and inp.g_expression:
            try:
                import sympy as sp

                x = sp.Symbol(inp.variable)
                parsed_f = rt.evaluate(
                    inp.expression,
                    {inp.variable: inp.variable},
                    timeout=inp.timeout,
                    simplify_result=False,
                )
                parsed_g = rt.evaluate(
                    inp.g_expression,
                    {inp.variable: inp.variable},
                    timeout=inp.timeout,
                    simplify_result=False,
                )
                if not parsed_f.success or parsed_f.value is None:
                    result_str = f"error: {parsed_f.error}"
                elif not parsed_g.success or parsed_g.value is None:
                    result_str = f"error: {parsed_g.error}"
                else:
                    fog = parsed_f.value.subs(x, parsed_g.value)
                    simplified = sp.simplify(fog)
                    result_str = str(simplified)
            except Exception as e:
                result_str = f"error: {e}"
            steps.append(
                SolveStep(
                    step_number=2,
                    description=f"Compose f∘g where g={inp.g_expression}",
                    expression=f"f({inp.g_expression})",
                    result=result_str,
                )
            )
            answer = f"f∘g = {result_str}"

        elif task == "monotonicity":
            try:
                import sympy as sp

                x = sp.Symbol(inp.variable)
                parsed = rt.evaluate(
                    inp.expression,
                    {inp.variable: inp.variable},
                    timeout=inp.timeout,
                    simplify_result=False,
                )
                if not parsed.success or parsed.value is None:
                    result_str = str(parsed.error)
                else:
                    df = sp.diff(parsed.value, x)
                    critical = sp.solve(df, x)
                    result_str = f"f'(x) = {df}; critical points: {critical}"
            except Exception as e:
                result_str = str(e)
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Find monotonicity via derivative",
                    expression=f"d/dx({inp.expression})",
                    result=result_str,
                )
            )
            answer = result_str

        elif task == "inverse":
            try:
                import sympy as sp

                x = sp.Symbol(inp.variable)
                y = sp.Symbol("y")
                parsed = rt.evaluate(
                    inp.expression,
                    {inp.variable: inp.variable},
                    timeout=inp.timeout,
                    simplify_result=False,
                )
                if not parsed.success or parsed.value is None:
                    result_str = str(parsed.error)
                else:
                    inv = sp.solve(parsed.value - y, x)
                    result_str = str(inv)
            except Exception as e:
                result_str = str(e)
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Find inverse function",
                    expression=f"solve({inp.expression}=y for x)",
                    result=result_str,
                )
            )
            answer = f"f⁻¹(y) = {result_str}"

        else:
            return SolveResult(
                solvable=False,
                answer="",
                steps=steps,
                error=f"Unknown task: {task}",
                raw_expression=inp.expression,
            )

        latex_result = rt.to_latex(inp.expression, timeout=inp.timeout)
        sol_latex = latex_result.result_str if latex_result.success else inp.expression

        return SolveResult(
            solvable=True,
            answer=answer,
            steps=steps,
            method="kernel",
            raw_expression=inp.expression,
            solution_latex=sol_latex,
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
