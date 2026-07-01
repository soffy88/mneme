"""Grade a student answer — deterministic kernel first, LLM fallback.

Async.  If solve_result is solvable, uses deterministic comparison (method="kernel").
Only falls back to LLM when kernel cannot determine correctness.

Version: oprim v3.5.0
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

from oprim.types import GradeResult, SolveResult


@dataclass
class GradeQuestionInput:
    """Input for grading a student answer.

    Attributes
    ----------
    question : str
        The question text.
    student_answer : str
        The student's answer.
    expected_answer : str | None
        Explicit expected answer (takes precedence over solve_result).
    solve_result : SolveResult | None
        Kernel solve result — if solvable, comparison is deterministic.
    subject : str
        Subject area hint ("math", "physics", etc.).
    grade_level : str
        Student grade level ("中学", "高中", "大学", etc.).
    system : str | None
        Optional system prompt override.
    """

    question: str
    student_answer: str
    expected_answer: str | None = None
    solve_result: SolveResult | None = None
    subject: str = "math"
    grade_level: str = "中学"
    system: str | None = None


def _normalize(s: str) -> str:
    """Normalise answer string for comparison."""
    s = s.strip().lower()
    s = re.sub(r"\s+", "", s)
    s = s.replace("×", "*").replace("÷", "/").replace("−", "-")
    s = s.replace("π", "pi")
    return s


def _compare_answer(student: str, expected: str) -> bool:
    """Deterministic answer comparison."""
    norm_s = _normalize(student)
    norm_e = _normalize(expected)
    if norm_s == norm_e:
        return True

    # Try numeric comparison
    try:
        fs = float(norm_s)
        fe = float(norm_e)
        return abs(fs - fe) < 1e-6 or (fe != 0 and abs((fs - fe) / fe) < 1e-4)
    except ValueError:
        pass

    # Try sympy equivalence
    try:
        import sympy as sp
        s_sym = sp.sympify(norm_s)
        e_sym = sp.sympify(norm_e)
        return sp.simplify(s_sym - e_sym) == 0
    except Exception:
        pass

    return False


_GRADE_SYSTEM = (
    "You are a math teacher grading a student's answer. "
    "Respond with JSON: {\"is_correct\": bool, \"score\": float 0-1, \"feedback\": str}. "
    "Be concise and educational. Score 1.0 = fully correct, 0.5 = partially correct, 0 = wrong."
)


async def grade_question(
    inp: GradeQuestionInput,
    *,
    caller: Any,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 512,
) -> GradeResult:
    """Grade a student answer.

    Deterministic kernel path:
      If inp.solve_result is solvable, compare directly — no LLM call.
      If inp.expected_answer is given, compare directly — no LLM call.

    LLM fallback:
      Called only when no kernel/expected answer is available.

    Parameters
    ----------
    inp : GradeQuestionInput
    caller : Any
        LLMCaller protocol instance.
    model : str
    max_tokens : int

    Returns
    -------
    GradeResult
    """
    # ── Deterministic kernel path ─────────────────────────────────────────
    if inp.solve_result and inp.solve_result.solvable:
        is_correct = _compare_answer(inp.student_answer, inp.solve_result.answer)
        return GradeResult(
            is_correct=is_correct,
            method="kernel",
            score=1.0 if is_correct else 0.0,
            feedback="正确" if is_correct else f"参考答案: {inp.solve_result.answer}",
        )

    if inp.expected_answer is not None:
        is_correct = _compare_answer(inp.student_answer, inp.expected_answer)
        return GradeResult(
            is_correct=is_correct,
            method="kernel",
            score=1.0 if is_correct else 0.0,
            feedback="正确" if is_correct else f"参考答案: {inp.expected_answer}",
        )

    # ── LLM fallback ──────────────────────────────────────────────────────
    from oprim.llm._llm_complete import llm_complete

    prompt = (
        f"题目: {inp.question}\n"
        f"学生答案: {inp.student_answer}\n"
        f"年级: {inp.grade_level}, 科目: {inp.subject}\n"
        "请判断答案是否正确，返回 JSON。"
    )
    messages = [{"role": "user", "content": prompt}]
    system = inp.system or _GRADE_SYSTEM

    try:
        response = await llm_complete(
            messages,
            caller=caller,
            system=system,
            model=model,
            max_tokens=max_tokens,
        )

        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip().rstrip("`")

        data = json.loads(raw)
        return GradeResult(
            is_correct=bool(data.get("is_correct", False)),
            method="llm",
            score=float(data.get("score", 0.0)),
            feedback=data.get("feedback", ""),
        )

    except Exception as exc:
        return GradeResult(
            is_correct=False,
            method="llm",
            score=0.0,
            error=str(exc),
        )
