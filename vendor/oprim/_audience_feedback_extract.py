"""oprim.audience_feedback_extract — LLM-based feedback extraction from comments.

Example:
    >>> from oprim.audience_feedback_extract import audience_feedback_extract
    >>> fb = await audience_feedback_extract(comments=["Too fast!"], llm=my_llm)

Raises:
    FeedbackExtractError: Extraction failed.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


class FeedbackExtractError(Exception):
    """Feedback extraction failed."""


class AudienceFeedback(BaseModel):
    """Structured audience feedback."""

    positive_points: list[str]
    negative_points: list[str]
    questions: list[str]
    suggestions: list[str]


async def audience_feedback_extract(
    *,
    comments: list[str],
    llm: Any,
) -> AudienceFeedback:
    """Extract structured feedback from audience comments via LLM.

    Args:
        comments: List of comment texts.
        llm: LLMCaller protocol instance.

    Returns:
        AudienceFeedback with categorized points.

    Raises:
        FeedbackExtractError: Empty comments, LLM failure, or invalid response.

    Example:
        >>> fb = await audience_feedback_extract(comments=["Great!"], llm=llm)
    """
    if not comments:
        raise FeedbackExtractError("comments must not be empty")

    messages = [
        {"role": "system", "content": (
            "Extract structured feedback from comments. "
            "Return JSON: {\"positive_points\": [str], \"negative_points\": [str], "
            "\"questions\": [str], \"suggestions\": [str]}."
        )},
        {"role": "user", "content": "\n".join(comments[:200])},
    ]

    try:
        result = llm(messages=messages)
    except Exception as exc:
        raise FeedbackExtractError(f"LLM call failed: {exc}") from exc

    content = result.get("content", "")
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise FeedbackExtractError(f"LLM returned invalid JSON: {content[:200]}") from exc

    try:
        return AudienceFeedback.model_validate(data)
    except Exception as exc:
        raise FeedbackExtractError(f"Validation failed: {exc}") from exc
