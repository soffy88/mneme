"""Solve sequence problems using SymPy and math.

Pure deterministic kernel — no LLM calls.
Handles: arithmetic sequences, geometric sequences, nth-term formulas,
partial sums, recurrence relations.

Version: oprim v3.4.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from obase.sympy_runtime import SymPyRuntime

from oprim.types import SolveResult, SolveStep

_runtime = SymPyRuntime()


SequenceType = Literal["arithmetic", "geometric", "auto"]
TaskType = Literal["nth_term", "sum", "type_check", "auto"]


@dataclass(frozen=True)
class SequenceSolveInput:
    """Input for a sequence problem."""

    terms: list[float]  # known terms (at least 2)
    n: int | None = None  # target index for nth_term
    count: int | None = None  # number of terms for sum
    task: TaskType = "auto"
    timeout: float = 5.0


def _detect_arithmetic(terms: list[float]) -> tuple[bool, float, float]:
    """Return (is_arith, first_term, common_diff)."""
    if len(terms) < 2:
        return False, 0.0, 0.0
    diffs = [terms[i + 1] - terms[i] for i in range(len(terms) - 1)]
    if all(abs(d - diffs[0]) < 1e-9 for d in diffs):
        return True, terms[0], diffs[0]
    return False, 0.0, 0.0


def _detect_geometric(terms: list[float]) -> tuple[bool, float, float]:
    """Return (is_geom, first_term, common_ratio)."""
    if len(terms) < 2:
        return False, 0.0, 0.0
    if any(abs(t) < 1e-12 for t in terms[:-1]):
        return False, 0.0, 0.0
    ratios = [terms[i + 1] / terms[i] for i in range(len(terms) - 1)]
    if all(abs(r - ratios[0]) < 1e-9 for r in ratios):
        return True, terms[0], ratios[0]
    return False, 0.0, 0.0


def solve_sequence(inp: SequenceSolveInput) -> SolveResult:
    """Solve a sequence problem deterministically.

    Parameters
    ----------
    inp : SequenceSolveInput

    Returns
    -------
    SolveResult
    """

    def _compute() -> SolveResult:
        steps: list[SolveStep] = []
        if not inp.terms or len(inp.terms) < 2:
            return SolveResult(
                solvable=False,
                answer="",
                steps=steps,
                error="Need at least 2 terms",
            )

        is_arith, a1, d = _detect_arithmetic(inp.terms)
        is_geom, g1, r = _detect_geometric(inp.terms)

        if is_arith:
            seq_type = "arithmetic"
            steps.append(
                SolveStep(
                    step_number=1,
                    description="Identified arithmetic sequence",
                    expression=f"a₁={a1}, d={d}",
                    result=f"a(n) = {a1} + (n-1)·{d}",
                )
            )
        elif is_geom:
            seq_type = "geometric"
            steps.append(
                SolveStep(
                    step_number=1,
                    description="Identified geometric sequence",
                    expression=f"a₁={g1}, r={r}",
                    result=f"a(n) = {g1}·{r}^(n-1)",
                )
            )
        else:
            seq_type = "unknown"
            steps.append(
                SolveStep(
                    step_number=1,
                    description="Sequence type not recognised",
                    expression=str(inp.terms),
                    result="unknown pattern",
                )
            )

        task = inp.task
        if task == "auto":
            task = (
                "nth_term"
                if inp.n is not None
                else "sum"
                if inp.count is not None
                else "type_check"
            )

        if task == "type_check":
            answer = f"type: {seq_type}"
            if is_arith:
                answer += f"; a₁={a1}, d={d}"
            elif is_geom:
                answer += f"; a₁={g1}, r={r}"
            return SolveResult(
                solvable=True,
                answer=answer,
                steps=steps,
                method="kernel",
                confidence=1.0,
            )

        if task == "nth_term":
            n = inp.n
            if n is None:
                return SolveResult(
                    solvable=False,
                    answer="",
                    steps=steps,
                    error="nth_term task requires n",
                )
            if is_arith:
                val = a1 + (n - 1) * d
                formula = f"{a1} + ({n}-1)·{d}"
            elif is_geom:
                val = g1 * (r ** (n - 1))
                formula = f"{g1}·{r}^({n}-1)"
            else:
                return SolveResult(
                    solvable=False,
                    answer="",
                    steps=steps,
                    error="Cannot compute nth term for unknown sequence type",
                )
            steps.append(
                SolveStep(
                    step_number=2,
                    description=f"Compute term a({n})",
                    expression=formula,
                    result=str(val),
                )
            )
            answer = f"a({n}) = {val:.6g}"

        elif task == "sum":
            count = inp.count or len(inp.terms)
            if is_arith:
                total = (count / 2) * (2 * a1 + (count - 1) * d)
                formula = f"({count}/2)·(2·{a1} + ({count}-1)·{d})"
            elif is_geom:
                if abs(r - 1) < 1e-12:
                    total = g1 * count
                    formula = f"{g1}·{count}"
                else:
                    total = g1 * (1 - r**count) / (1 - r)
                    formula = f"{g1}·(1-{r}^{count})/(1-{r})"
            else:
                total = sum(inp.terms[:count])
                formula = f"sum of first {count} given terms"
            steps.append(
                SolveStep(
                    step_number=2,
                    description=f"Compute partial sum S({count})",
                    expression=formula,
                    result=str(total),
                )
            )
            answer = f"S({count}) = {total:.6g}"

        else:
            return SolveResult(
                solvable=False,
                answer="",
                steps=steps,
                error=f"Unknown task: {task}",
            )

        return SolveResult(
            solvable=True,
            answer=answer,
            steps=steps,
            method="kernel",
            confidence=1.0,
        )

    try:
        return _runtime.run_isolated(_compute, timeout=inp.timeout)
    except Exception as exc:
        return SolveResult(
            solvable=False,
            answer="",
            steps=[],
            error=str(exc),
        )
