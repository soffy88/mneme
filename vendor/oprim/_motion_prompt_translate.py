"""oprim.motion_prompt_translate — LLM translation of motion description to video prompt.

Example:
    >>> from oprim.motion_prompt_translate import motion_prompt_translate
    >>> prompt = await motion_prompt_translate(
    ...     natural_language_motion="slow pan left", llm=my_llm,
    ... )

Raises:
    MotionTranslateError: Translation failed.
"""

from __future__ import annotations

from typing import Any, Protocol


class LLMCaller(Protocol):
    """Protocol for LLM caller functions."""

    def __call__(self, *, messages: list[dict[str, Any]]) -> dict[str, Any]: ...


class MotionTranslateError(Exception):
    """Motion prompt translation failed."""


async def motion_prompt_translate(
    *,
    natural_language_motion: str,
    llm: Any,
    target_provider: str = "wan22",
) -> str:
    """Translate natural language motion to video generation prompt.

    Args:
        natural_language_motion: Human-readable motion description.
        llm: LLMCaller protocol instance.
        target_provider: Target video provider for prompt style.

    Returns:
        Translated motion prompt string.

    Raises:
        MotionTranslateError: Empty input or LLM failure.

    Example:
        >>> result = await motion_prompt_translate(
        ...     natural_language_motion="slow pan left", llm=llm)
    """
    if not natural_language_motion.strip():
        raise MotionTranslateError("natural_language_motion must not be empty")

    messages = [
        {"role": "system", "content": (
            f"Translate the following camera/motion description into a video generation "
            f"prompt optimized for {target_provider}. Return ONLY the translated prompt, "
            f"no explanation."
        )},
        {"role": "user", "content": natural_language_motion},
    ]

    try:
        result = llm(messages=messages)
    except Exception as exc:
        raise MotionTranslateError(f"LLM call failed: {exc}") from exc

    content: str = str(result.get("content", "")).strip()
    if not content:
        raise MotionTranslateError("LLM returned empty translation")
    return content
