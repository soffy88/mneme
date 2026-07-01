"""Find common error breakpoints across a set of wrong student answers.

Async, single LLM call.
If wrong_questions is empty, returns immediately (no LLM call).

Version: oprim v3.5.0
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WrongQuestion:
    """A single wrong answer record."""

    question_id: str
    question_text: str
    student_answer: str
    correct_answer: str
    kc_ids: list[str] = field(default_factory=list)
    error_type: str = ""  # pre-classified error if available


@dataclass(frozen=True)
class BreakpointResult:
    """Common error breakpoints found across wrong answers.

    Attributes
    ----------
    breakpoints : list[dict]
        Each dict: {kc_id, error_pattern, frequency, description, remedy}.
    dominant_error_type : str
        The most frequent error category.
    affected_question_ids : list[str]
        Question IDs affected by the dominant breakpoint.
    summary : str
        Brief prose summary.
    success : bool
    error : str
    """

    breakpoints: list[dict] = field(default_factory=list)
    dominant_error_type: str = ""
    affected_question_ids: list[str] = field(default_factory=list)
    summary: str = ""
    success: bool = True
    error: str = ""


_BREAKPOINT_SYSTEM = (
    "You are a math education diagnostic specialist. Analyze a set of wrong student "
    "answers to identify common error patterns and cognitive breakpoints. "
    "Respond with JSON: "
    '{"breakpoints": [{"kc_id": str, "error_pattern": str, "frequency": int, '
    '"description": str, "remedy": str}], '
    '"dominant_error_type": str, "affected_question_ids": [str], "summary": str}.'
)


async def find_common_breakpoint(
    wrong_questions: list[WrongQuestion],
    *,
    caller: Any,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 1024,
    system: str | None = None,
) -> BreakpointResult:
    """Find common cognitive breakpoints across wrong answers.

    Short-circuits immediately (no LLM) if wrong_questions is empty.

    Parameters
    ----------
    wrong_questions : list[WrongQuestion]
        Collection of wrong answer records to analyze.
    caller : Any
    model : str
    max_tokens : int
    system : str | None

    Returns
    -------
    BreakpointResult
    """
    if not wrong_questions:
        return BreakpointResult(
            breakpoints=[],
            dominant_error_type="",
            affected_question_ids=[],
            summary="No wrong questions provided.",
            success=True,
        )

    from oprim.llm._llm_complete import llm_complete

    questions_data = [
        {
            "id": wq.question_id,
            "question": wq.question_text,
            "student_answer": wq.student_answer,
            "correct_answer": wq.correct_answer,
            "kc_ids": wq.kc_ids,
            "error_type": wq.error_type,
        }
        for wq in wrong_questions
    ]

    prompt = (
        f"以下是 {len(wrong_questions)} 道错误答题记录，请找出共同的错误断点:\n"
        + json.dumps(questions_data, ensure_ascii=False, indent=2)
        + "\n\n请返回 JSON 格式的分析结果。"
    )
    messages = [{"role": "user", "content": prompt}]

    try:
        response = await llm_complete(
            messages,
            caller=caller,
            system=system or _BREAKPOINT_SYSTEM,
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
        return BreakpointResult(
            breakpoints=data.get("breakpoints", []),
            dominant_error_type=data.get("dominant_error_type", ""),
            affected_question_ids=data.get("affected_question_ids", []),
            summary=data.get("summary", ""),
            success=True,
        )

    except Exception as exc:
        return BreakpointResult(success=False, error=str(exc))
