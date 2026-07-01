from __future__ import annotations

from typing import Literal

from obase import ProviderRegistry
from pydantic import BaseModel

from oprim._exceptions import OprimError


class SummarizeResult(BaseModel):
    summary: str
    tokens_used: int
    provider: str


def llm_summarize(
    *,
    text: str,
    max_length: int = 500,
    provider: str = "qwen3",
    model: str = "qwen3-max",
    style: Literal["concise", "detailed", "bullet_points"] = "concise",
) -> SummarizeResult:
    """Generate a summary of the input text using a single LLM call.

    Single LLM call = oprim (not oskill). Caller controls retry/caching.

    Args:
        text: Input text to summarize
        max_length: Maximum length of summary in words (approximate)
        provider: LLM provider name (routed via obase.ProviderRegistry)
        model: Model identifier
        style: Summary style — "concise" | "detailed" | "bullet_points"

    Returns:
        SummarizeResult with summary, tokens_used, provider

    Raises:
        OprimError: LLM call failed or provider not configured

    Example:
        >>> result = llm_summarize(text="Long text here...", provider="qwen3")
        >>> len(result.summary) > 0
        True
    """
    if not text.strip():
        return SummarizeResult(summary="", tokens_used=0, provider=provider)

    style_instructions = {
        "concise": f"Summarize in {max_length} words or fewer. Be concise.",
        "detailed": f"Summarize in up to {max_length} words with full detail.",
        "bullet_points": f"Summarize as bullet points, max {max_length} words total.",
    }

    prompt = f"{style_instructions[style]}\n\nText:\n{text}"

    try:
        caller = ProviderRegistry.get().llm(provider)
        response = caller(messages=[{"role": "user", "content": prompt}])

        # Handle different response formats
        if isinstance(response, str):
            summary = response
            tokens_used = len(response.split())
        elif isinstance(response, dict):
            raw: object = response.get("content") or response.get("text") or str(response)
            summary = str(raw)
            usage_raw: object = response.get("usage", {})
            usage_dict = usage_raw if isinstance(usage_raw, dict) else {}
            total: object = usage_dict.get("total_tokens")
            tokens_used = int(total) if isinstance(total, int) else len(summary.split())
        else:
            summary = str(response)
            tokens_used = len(summary.split())

        return SummarizeResult(summary=summary, tokens_used=tokens_used, provider=provider)
    except OprimError:
        raise
    except Exception as e:
        raise OprimError(f"llm_summarize failed: {e}") from e
