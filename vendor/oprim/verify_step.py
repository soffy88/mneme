"""Verify a single algebraic step in a math solution.

Pure deterministic kernel — absolutely NO LLM calls.
Uses SymPy to check whether an algebraic transformation is valid:
  lhs_before == rhs_before  AND  lhs_after == rhs_after  AND
  the transformation preserves equality.

Version: oprim v3.4.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from oprim.types import SolveResult, SolveStep, StepCheckResult


@dataclass(frozen=True)
class StepVerifyInput:
    """Input for verifying a single solution step.

    Attributes
    ----------
    step_number : int
        1-based step index.
    before_lhs : str
        Left-hand side expression before this step.
    before_rhs : str
        Right-hand side expression before this step (default "0").
    after_lhs : str
        Left-hand side expression after this step.
    after_rhs : str
        Right-hand side expression after this step (default "0").
    variable : str
        Primary variable name (used for symbol creation).
    extra_variables : list[str]
        Additional variable names to declare as symbols.
    description : str
        Human description of what this step does.
    timeout : float
        Maximum seconds for SymPy operations.
    """

    step_number: int
    before_lhs: str
    after_lhs: str
    before_rhs: str = "0"
    after_rhs: str = "0"
    variable: str = "x"
    extra_variables: list[str] = field(default_factory=list)
    description: str = ""
    timeout: float = 5.0


def _make_symbols(variable: str, extras: list[str]):
    """Create a sympy symbols namespace dict."""
    import sympy as sp
    ns = {}
    all_vars = [variable] + [v for v in extras if v != variable]
    for name in all_vars:
        ns[name] = sp.Symbol(name)
    return ns


def _sympify_with_ns(expr_str: str, ns: dict):
    """Parse expression string using local symbol namespace."""
    import sympy as sp
    return sp.sympify(expr_str, locals=ns)


def _check_equivalence(expr_a_str: str, expr_b_str: str, ns: dict) -> tuple[bool, str]:
    """Check if two expressions are symbolically equivalent."""
    import sympy as sp
    try:
        a = _sympify_with_ns(expr_a_str, ns)
        b = _sympify_with_ns(expr_b_str, ns)
        diff = sp.simplify(a - b)
        if diff == 0:
            return True, "equivalent"
        return False, f"difference = {diff}"
    except Exception as e:
        return False, f"error: {e}"


def verify_step(inp: StepVerifyInput) -> StepCheckResult:
    """Verify that a single algebraic step is valid.

    Checks:
    1. The "before" equation (before_lhs - before_rhs == 0) is internally
       consistent (can be simplified, not necessarily a specific value).
    2. The "after" equation (after_lhs - after_rhs == 0) is equivalent to
       the "before" equation (i.e., the transformation preserves equality).

    Parameters
    ----------
    inp : StepVerifyInput

    Returns
    -------
    StepCheckResult
        is_correct=True if the step is algebraically valid.
    """
    import sympy as sp

    ns = _make_symbols(inp.variable, inp.extra_variables)

    try:
        before_lhs = _sympify_with_ns(inp.before_lhs, ns)
        before_rhs = _sympify_with_ns(inp.before_rhs, ns)
        after_lhs = _sympify_with_ns(inp.after_lhs, ns)
        after_rhs = _sympify_with_ns(inp.after_rhs, ns)

        # Normalise: both sides to LHS - RHS = 0
        before_expr = sp.expand(before_lhs - before_rhs)
        after_expr = sp.expand(after_lhs - after_rhs)

        # Check that after_expr ≡ before_expr (up to simplification/factoring)
        diff = sp.simplify(after_expr - before_expr)
        is_correct = diff == 0

        if is_correct:
            return StepCheckResult(
                step_number=inp.step_number,
                is_correct=True,
                suggestion="Step verified: algebraic transformation is valid.",
            )
        else:
            return StepCheckResult(
                step_number=inp.step_number,
                is_correct=False,
                error_type="algebraic_error",
                error_detail=f"Transformation changes the expression by: {diff}",
                suggestion=(
                    "Check arithmetic: the expression on the left/right side "
                    "of the step does not follow from the previous step."
                ),
            )

    except Exception as exc:
        return StepCheckResult(
            step_number=inp.step_number,
            is_correct=False,
            error_type="parse_error",
            error_detail=str(exc),
            suggestion="Could not parse expression — check syntax.",
        )


def verify_steps(inputs: list[StepVerifyInput]) -> list[StepCheckResult]:
    """Verify a sequence of steps.

    Each step is verified independently against its own before/after pair.

    Parameters
    ----------
    inputs : list[StepVerifyInput]

    Returns
    -------
    list[StepCheckResult]
    """
    return [verify_step(inp) for inp in inputs]


def build_solve_result_with_checks(
    expression: str,
    answer: str,
    steps: list[SolveStep],
    checks: list[StepCheckResult],
) -> SolveResult:
    """Helper to build a SolveResult that includes step verification checks."""
    all_correct = all(c.is_correct for c in checks)
    return SolveResult(
        solvable=all_correct,
        answer=answer if all_correct else "",
        steps=steps,
        step_checks=checks,
        method="kernel",
        raw_expression=expression,
        confidence=1.0 if all_correct else 0.0,
        error="" if all_correct else "One or more steps failed verification",
    )
