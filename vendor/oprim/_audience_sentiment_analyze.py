"""oprim.audience_sentiment_analyze — LLM-based comment sentiment analysis.

Example:
    >>> from oprim.audience_sentiment_analyze import audience_sentiment_analyze
    >>> result = await audience_sentiment_analyze(comments=["Great video!"], llm=my_llm)

Raises:
    SentimentAnalyzeError: Analysis failed.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


class SentimentAnalyzeError(Exception):
    """Sentiment analysis failed."""


class SentimentResult(BaseModel):
    """Sentiment analysis output."""

    positive_pct: float
    negative_pct: float
    neutral_pct: float
    top_keywords: list[str]


async def audience_sentiment_analyze(
    *,
    comments: list[str],
    llm: Any,
) -> SentimentResult:
    """Analyze sentiment of audience comments via LLM.

    Args:
        comments: List of comment texts.
        llm: LLMCaller protocol instance.

    Returns:
        SentimentResult with percentages and keywords.

    Raises:
        SentimentAnalyzeError: Empty comments, LLM failure, or invalid response.

    Example:
        >>> r = await audience_sentiment_analyze(comments=["nice!"], llm=llm)
    """
    if not comments:
        raise SentimentAnalyzeError("comments must not be empty")

    messages = [
        {"role": "system", "content": (
            "Analyze sentiment of the following comments. "
            "Return JSON: {\"positive_pct\": float, \"negative_pct\": float, "
            "\"neutral_pct\": float, \"top_keywords\": [str]}. "
            "Percentages must sum to 1.0."
        )},
        {"role": "user", "content": "\n".join(comments[:200])},
    ]

    try:
        result = llm(messages=messages)
    except Exception as exc:
        raise SentimentAnalyzeError(f"LLM call failed: {exc}") from exc

    content = result.get("content", "")
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SentimentAnalyzeError(f"LLM returned invalid JSON: {content[:200]}") from exc

    try:
        return SentimentResult.model_validate(data)
    except Exception as exc:
        raise SentimentAnalyzeError(f"Validation failed: {exc}") from exc
