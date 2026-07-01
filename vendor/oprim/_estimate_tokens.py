"""LLM token estimation without an external tokenizer."""
from __future__ import annotations


def estimate_tokens(text: str, *, model: str) -> int:
    """Estimate the number of tokens in *text* for the given *model*.

    No external tokenizer is required.  The estimate is intentionally
    conservative:

    * Claude models tokenise multi-byte scripts (Chinese, Japanese, …) more
      aggressively, so a smaller ratio (3.5 chars per token) is used.
    * GPT and unknown models use the looser ratio of 4 chars per token.

    Multi-byte characters are counted as single codepoints (``len(text)``),
    not as raw bytes.

    Parameters
    ----------
    text:
        The text whose tokens are to be estimated.
    model:
        Model identifier string (e.g. ``"claude-3-5-sonnet-20241022"``).

    Returns
    -------
    int
        Estimated token count, always >= 0.
    """
    if not text:
        return 0

    ratio: float = 3.5 if "claude" in model.lower() else 4.0
    return max(0, int(len(text) / ratio))
