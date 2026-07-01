"""Solve probability problems using math and SymPy.

Pure deterministic kernel — no LLM calls.
Handles: basic probability, combinations, permutations, conditional probability,
Bayes theorem, binomial distribution, expected value.

Version: oprim v3.4.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from oprim.types import SolveResult, SolveStep


TaskType = Literal[
    "combinations", "permutations", "basic", "conditional",
    "bayes", "binomial", "expected_value", "auto"
]


@dataclass(frozen=True)
class ProbabilitySolveInput:
    """Input for a probability problem."""

    task: TaskType = "auto"
    n: int | None = None               # total items / trials
    k: int | None = None               # chosen items / successes
    p_a: float | None = None           # P(A)
    p_b: float | None = None           # P(B)
    p_a_given_b: float | None = None   # P(A|B)
    p_b_given_a: float | None = None   # P(B|A)
    p_success: float | None = None     # p per trial (binomial)
    values: list[float] | None = None  # for expected value
    probabilities: list[float] | None = None  # for expected value
    timeout: float = 5.0


def solve_probability(inp: ProbabilitySolveInput) -> SolveResult:
    """Solve a probability problem deterministically.

    Parameters
    ----------
    inp : ProbabilitySolveInput

    Returns
    -------
    SolveResult
    """
    steps: list[SolveStep] = []

    task = inp.task
    if task == "auto":
        if inp.n is not None and inp.k is not None and inp.p_success is None:
            task = "combinations"
        elif inp.p_a is not None and inp.p_b is not None:
            task = "basic"
        elif inp.values is not None:
            task = "expected_value"
        else:
            task = "combinations"

    try:
        if task == "combinations":
            if inp.n is None or inp.k is None:
                raise ValueError("combinations task requires n and k")
            n, k = int(inp.n), int(inp.k)
            result = math.comb(n, k)
            steps.append(
                SolveStep(
                    step_number=1,
                    description=f"Compute C({n},{k}) = n! / (k!·(n-k)!)",
                    expression=f"C({n},{k})",
                    result=str(result),
                )
            )
            answer = f"C({n},{k}) = {result}"

        elif task == "permutations":
            if inp.n is None or inp.k is None:
                raise ValueError("permutations task requires n and k")
            n, k = int(inp.n), int(inp.k)
            result = math.perm(n, k)
            steps.append(
                SolveStep(
                    step_number=1,
                    description=f"Compute P({n},{k}) = n! / (n-k)!",
                    expression=f"P({n},{k})",
                    result=str(result),
                )
            )
            answer = f"P({n},{k}) = {result}"

        elif task == "basic":
            if inp.p_a is None or inp.p_b is None:
                raise ValueError("basic task requires p_a and p_b")
            p_a = inp.p_a
            p_b = inp.p_b
            p_a_and_b = p_a * p_b  # assuming independence
            p_a_or_b = p_a + p_b - p_a_and_b
            steps.append(
                SolveStep(
                    step_number=1,
                    description="Compute P(A∩B) assuming independence",
                    expression=f"P(A)·P(B) = {p_a}·{p_b}",
                    result=f"{p_a_and_b:.6g}",
                )
            )
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Compute P(A∪B) = P(A) + P(B) - P(A∩B)",
                    expression=f"{p_a} + {p_b} - {p_a_and_b:.6g}",
                    result=f"{p_a_or_b:.6g}",
                )
            )
            answer = (
                f"P(A∩B) = {p_a_and_b:.6g}; "
                f"P(A∪B) = {p_a_or_b:.6g}; "
                f"P(Ā) = {1-p_a:.6g}"
            )

        elif task == "conditional":
            if inp.p_a_given_b is None and inp.p_b_given_a is None:
                raise ValueError("conditional task requires p_a_given_b or p_b_given_a")
            if inp.p_a is None or inp.p_b is None:
                raise ValueError("conditional task requires p_a and p_b")
            if inp.p_b_given_a is not None:
                p_a_and_b = inp.p_b_given_a * inp.p_a
                p_a_given_b = p_a_and_b / inp.p_b if abs(inp.p_b) > 1e-12 else 0.0
                steps.append(
                    SolveStep(
                        step_number=1,
                        description="P(A∩B) = P(B|A)·P(A)",
                        expression=f"{inp.p_b_given_a}·{inp.p_a}",
                        result=f"{p_a_and_b:.6g}",
                    )
                )
                steps.append(
                    SolveStep(
                        step_number=2,
                        description="P(A|B) = P(A∩B)/P(B)",
                        expression=f"{p_a_and_b:.6g}/{inp.p_b}",
                        result=f"{p_a_given_b:.6g}",
                    )
                )
                answer = f"P(A|B) = {p_a_given_b:.6g}"
            else:
                answer = f"P(A|B) = {inp.p_a_given_b:.6g} (given)"

        elif task == "bayes":
            if inp.p_a is None or inp.p_b_given_a is None or inp.p_b is None:
                raise ValueError("bayes task requires p_a, p_b_given_a, p_b")
            p_b_given_a = inp.p_b_given_a
            p_a = inp.p_a
            p_b = inp.p_b
            p_a_given_b = (p_b_given_a * p_a) / p_b
            steps.append(
                SolveStep(
                    step_number=1,
                    description="Apply Bayes theorem: P(A|B) = P(B|A)·P(A)/P(B)",
                    expression=f"({p_b_given_a}·{p_a})/{p_b}",
                    result=f"{p_a_given_b:.6g}",
                )
            )
            answer = f"P(A|B) = {p_a_given_b:.6g}"

        elif task == "binomial":
            if inp.n is None or inp.k is None or inp.p_success is None:
                raise ValueError("binomial task requires n, k, p_success")
            n, k = int(inp.n), int(inp.k)
            p = inp.p_success
            prob = math.comb(n, k) * (p**k) * ((1-p)**(n-k))
            mean = n * p
            var = n * p * (1 - p)
            steps.append(
                SolveStep(
                    step_number=1,
                    description=f"Binomial: P(X={k}) = C({n},{k})·p^k·(1-p)^(n-k)",
                    expression=f"C({n},{k})·{p}^{k}·{1-p}^{n-k}",
                    result=f"{prob:.6g}",
                )
            )
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Mean and variance",
                    expression=f"E[X]=np={n}·{p}, Var=np(1-p)",
                    result=f"E[X]={mean:.4g}, Var={var:.4g}",
                )
            )
            answer = f"P(X={k}) = {prob:.6g}; E[X] = {mean:.4g}; Var = {var:.4g}"

        elif task == "expected_value":
            if inp.values is None or inp.probabilities is None:
                raise ValueError("expected_value task requires values and probabilities")
            if len(inp.values) != len(inp.probabilities):
                raise ValueError("values and probabilities must have same length")
            total_p = sum(inp.probabilities)
            if abs(total_p - 1.0) > 1e-6:
                raise ValueError(f"probabilities must sum to 1 (got {total_p})")
            ev = sum(v * p for v, p in zip(inp.values, inp.probabilities))
            ev2 = sum(v**2 * p for v, p in zip(inp.values, inp.probabilities))
            var = ev2 - ev**2
            steps.append(
                SolveStep(
                    step_number=1,
                    description="Compute E[X] = Σ xᵢ·pᵢ",
                    expression=str(list(zip(inp.values, inp.probabilities))),
                    result=f"{ev:.6g}",
                )
            )
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Compute Var[X] = E[X²] - E[X]²",
                    expression=f"E[X²]={ev2:.4g}, E[X]²={ev**2:.4g}",
                    result=f"{var:.6g}",
                )
            )
            answer = f"E[X] = {ev:.6g}; Var[X] = {var:.6g}"

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

    except Exception as exc:
        return SolveResult(
            solvable=False,
            answer="",
            steps=steps,
            error=str(exc),
        )
