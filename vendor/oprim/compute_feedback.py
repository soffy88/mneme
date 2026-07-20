"""Compute deterministic feedback for student answers.

Pure algorithm, no LLM.  Compares student answers to expected answers
and generates structured feedback with hints.

Version: oprim v3.3.0
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from obase.sympy_runtime import SymPyRuntime
from oprim.types import GradeResult, SolveResult

_runtime = SymPyRuntime()


@dataclass(frozen=True)
class FeedbackItem:
    """A single feedback item for a student answer."""

    category: str  # "correct" | "partial" | "incorrect" | "format_error"
    message: str
    hint: str = ""
    expected: str = ""
    got: str = ""
    score: float = 0.0  # 0..1


def compute_feedback(
    student_answer: str,
    solve_result: SolveResult | None = None,
    *,
    expected_answer: str | None = None,
    case_sensitive: bool = False,
    strip_whitespace: bool = True,
) -> FeedbackItem:
    """Generate deterministic feedback by comparing student to expected answer.

    If solve_result is provided and solvable, its answer is used as the
    expected answer (deterministic kernel comparison).  If expected_answer
    is explicitly provided, it takes precedence over solve_result.answer.

    Parameters
    ----------
    student_answer : str
        The student's answer string.
    solve_result : SolveResult | None
        Optional kernel solve result for deterministic comparison.
    expected_answer : str | None
        Explicit expected answer (overrides solve_result.answer).
    case_sensitive : bool
        Whether comparison is case-sensitive.
    strip_whitespace : bool
        Whether to strip whitespace before comparing.

    Returns
    -------
    FeedbackItem
        Structured feedback with category, message, hint, and score.
    """
    # Determine expected answer
    expected = expected_answer
    if expected is None and solve_result is not None and solve_result.solvable:
        expected = solve_result.answer

    # Normalise
    s = _normalise(student_answer, case_sensitive, strip_whitespace)

    if expected is not None:
        e = _normalise(expected, case_sensitive, strip_whitespace)
    else:
        e = None

    # Format check: student answer is empty
    if not s:
        return FeedbackItem(
            category="format_error",
            message="答案为空，请重新作答。",
            hint="请填写你的答案。",
            expected=expected or "",
            got=student_answer,
            score=0.0,
        )

    # Format check: contains obviously invalid characters
    if _has_invalid_format(student_answer):
        return FeedbackItem(
            category="format_error",
            message="答案格式有误，请检查输入。",
            hint="答案应为数字、分数或表达式，不含多余字符。",
            expected=expected or "",
            got=student_answer,
            score=0.0,
        )

    # No expected answer available → can only do format check
    if e is None:
        return FeedbackItem(
            category="partial",
            message="答案已提交，但无法自动判定正误。等待人工或 LLM 评审。",
            hint="",
            expected="",
            got=student_answer,
            score=0.5,
        )

    # Exact match
    if s == e:
        return FeedbackItem(
            category="correct",
            message="回答正确！",
            expected=expected or "",
            got=student_answer,
            score=1.0,
        )

    # Numeric comparison (tolerant)
    s_num = _try_parse_number(s)
    e_num = _try_parse_number(e)
    if s_num is not None and e_num is not None:
        if _numeric_close(s_num, e_num):
            return FeedbackItem(
                category="correct",
                message="回答正确！（数值近似）",
                expected=expected or "",
                got=student_answer,
                score=1.0,
            )
        else:
            diff = abs(s_num - e_num)
            return FeedbackItem(
                category="incorrect",
                message=f"数值不正确。你的答案与正确答案相差 {diff:.4g}。",
                hint="请检查计算过程中的数值运算。",
                expected=expected or "",
                got=student_answer,
                score=0.0,
            )

    # Symbolic comparison: check if they are mathematically equivalent
    # by trying to simplify the difference
    if _symbolic_equivalent(s, e):
        return FeedbackItem(
            category="correct",
            message="回答正确！（等价表达式）",
            expected=expected or "",
            got=student_answer,
            score=1.0,
        )

    # Not correct
    hint = _generate_hint(student_answer, expected or "", solve_result)
    return FeedbackItem(
        category="incorrect",
        message="回答不正确。",
        hint=hint,
        expected=expected or "",
        got=student_answer,
        score=0.0,
    )


def grade_answer(
    student_answer: str,
    solve_result: SolveResult | None = None,
    *,
    expected_answer: str | None = None,
) -> GradeResult:
    """Grade a student answer deterministically when possible.

    If solve_result is solvable, comparison is kernel-based (no LLM).
    Falls back to LLM grading only when kernel cannot determine correctness.

    Parameters
    ----------
    student_answer : str
        Student's answer.
    solve_result : SolveResult | None
        Kernel solve result.
    expected_answer : str | None
        Explicit expected answer.

    Returns
    -------
    GradeResult
        is_correct, method, score, feedback.
    """
    feedback = compute_feedback(
        student_answer,
        solve_result,
        expected_answer=expected_answer,
    )

    # Kernel-based grading when we have a reference answer
    if feedback.expected:
        return GradeResult(
            is_correct=feedback.category == "correct",
            method="kernel",
            score=feedback.score,
            feedback=feedback.message,
        )

    # No reference answer → would need LLM
    return GradeResult(
        is_correct=False,
        method="llm",
        score=0.5,
        feedback="需要 LLM 评审（无参考答案）。",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalise(s: str, case_sensitive: bool, strip_whitespace: bool) -> str:
    """Normalise a string for comparison."""
    result = s.strip() if strip_whitespace else s
    if not case_sensitive:
        result = result.lower()
    # Remove common formatting: spaces, commas in numbers
    result = re.sub(r"\s+", "", result)
    result = result.replace(",", "")
    return result


def _has_invalid_format(s: str) -> bool:
    """Check for obviously invalid format."""
    stripped = s.strip()
    if not stripped:
        return False  # empty is handled separately
    # If it's purely non-alphanumeric garbage
    if re.match(r"^[^a-zA-Z0-9]+$", stripped):
        return True
    return False


def _try_parse_number(s: str) -> float | None:
    """Try to parse a string as a number."""
    try:
        return float(s)
    except (ValueError, TypeError):
        pass
    # Try fractions like "1/3"
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 2:
            try:
                num = float(parts[0])
                den = float(parts[1])
                if den != 0:
                    return num / den
            except (ValueError, TypeError):
                pass
    # Try expressions like "sqrt(2)" — approximate (S0-W5: s is the real
    # student answer, external input — was a raw sympy.sympify(), same bug
    # class S0 fixed in the 7 solve_* kernels).
    try:
        result = _runtime.evaluate_auto(s, simplify_result=False)
        if result.success and result.value is not None and result.value.is_number:
            return float(result.value.evalf())
    except Exception:
        pass
    return None


def _numeric_close(
    a: float, b: float, rel_tol: float = 1e-6, abs_tol: float = 1e-8
) -> bool:
    """Check if two numbers are approximately equal."""
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)


def _symbolic_equivalent(s: str, e: str) -> bool:
    """Check if two expression strings are symbolically equivalent.

    S0-W5: s/e are the real student answer / expected answer — external
    input, was raw sympy.sympify(), same bug class S0 fixed in the 7
    solve_* kernels.
    """
    try:
        import sympy

        result_s = _runtime.evaluate_auto(s, simplify_result=False)
        result_e = _runtime.evaluate_auto(e, simplify_result=False)
        if not (result_s.success and result_e.success):
            return False
        if result_s.value is None or result_e.value is None:
            return False
        diff = sympy.simplify(result_s.value - result_e.value)
        return diff == 0
    except Exception:
        return False


def _generate_hint(
    student_answer: str,
    expected: str,
    solve_result: SolveResult | None,
) -> str:
    """Generate a helpful hint based on the error pattern."""
    if solve_result and solve_result.steps:
        # Point to the last step
        last_step = solve_result.steps[-1]
        return f"请检查最后一步: {last_step.description}"

    # Generic hints based on pattern
    if "/" in student_answer and "/" in expected:
        return "注意约分是否正确。"
    if "^" in student_answer or "**" in student_answer:
        return "检查指数运算规则。"
    if "-" in student_answer and "+" in expected:
        return "注意符号是否正确。"
    return "请重新检查计算过程。"
