"""Evaluate a student-drawn diagram or graph using a VLM.

Async, single VLM call.  Returns structured feedback on diagram quality.

Version: oprim v3.5.0
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DiagramEvalInput:
    """Input for evaluating a student diagram.

    Attributes
    ----------
    image_b64 : str
        Base-64 encoded image of the student's diagram.
    image_url : str | None
        Alternative URL for the image.
    question : str
        The question that required the diagram.
    expected_elements : list[str]
        Key elements that should appear in the diagram.
    diagram_type : str
        Type of diagram ("coordinate_plane", "geometric_figure", "graph", "other").
    subject : str
    system : str | None
    """

    image_b64: str = ""
    image_url: str | None = None
    question: str = ""
    expected_elements: list[str] = field(default_factory=list)
    diagram_type: str = "geometric_figure"
    subject: str = "math"
    system: str | None = None


@dataclass(frozen=True)
class DiagramEvalResult:
    """Result of evaluating a student diagram.

    Attributes
    ----------
    is_correct : bool
        Whether the diagram correctly answers the question.
    score : float
        0..1 correctness score.
    missing_elements : list[str]
        Required elements not found in the diagram.
    extra_elements : list[str]
        Unexpected/incorrect elements.
    feedback : str
        Educational feedback for the student.
    suggestions : list[str]
        Specific improvement suggestions.
    success : bool
    error : str
    """

    is_correct: bool = False
    score: float = 0.0
    missing_elements: list[str] = field(default_factory=list)
    extra_elements: list[str] = field(default_factory=list)
    feedback: str = ""
    suggestions: list[str] = field(default_factory=list)
    success: bool = True
    error: str = ""


_EVAL_SYSTEM = (
    "You are a math teacher evaluating a student's hand-drawn diagram. "
    "Assess whether the diagram correctly represents the mathematical concept "
    "and contains all required elements. "
    "Return JSON: {\"is_correct\": bool, \"score\": float 0-1, "
    '"missing_elements\": [str], "extra_elements\": [str], '
    '"feedback\": str, "suggestions\": [str]}.'
)


async def evaluate_diagram(
    inp: DiagramEvalInput,
    *,
    caller: Any,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 1024,
) -> DiagramEvalResult:
    """Evaluate a student diagram using a VLM.

    Parameters
    ----------
    inp : DiagramEvalInput
    caller : Any
    model : str
    max_tokens : int

    Returns
    -------
    DiagramEvalResult
    """
    from oprim.llm._llm_complete import llm_complete

    if not inp.image_b64 and not inp.image_url:
        return DiagramEvalResult(
            success=False,
            error="Must provide image_b64 or image_url",
        )

    system = inp.system or _EVAL_SYSTEM

    # Build image content
    if inp.image_url:
        image_block = {
            "type": "image",
            "source": {"type": "url", "url": inp.image_url},
        }
    else:
        image_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": inp.image_b64,
            },
        }

    expected_str = ", ".join(inp.expected_elements) if inp.expected_elements else "未指定"
    text_block = {
        "type": "text",
        "text": (
            f"题目: {inp.question}\n"
            f"图形类型: {inp.diagram_type}\n"
            f"期望包含的元素: {expected_str}\n"
            "请评估该学生的图形，返回 JSON。"
        ),
    }

    messages = [{"role": "user", "content": [image_block, text_block]}]

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
        return DiagramEvalResult(
            is_correct=bool(data.get("is_correct", False)),
            score=float(data.get("score", 0.0)),
            missing_elements=data.get("missing_elements", []),
            extra_elements=data.get("extra_elements", []),
            feedback=data.get("feedback", ""),
            suggestions=data.get("suggestions", []),
            success=True,
        )

    except Exception as exc:
        return DiagramEvalResult(success=False, error=str(exc))
