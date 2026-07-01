"""oprim.vlm_video_analyze — VLM-based video frame analysis.

Example:
    >>> from oprim.vlm_video_analyze import vlm_video_analyze
    >>> desc = await vlm_video_analyze(
    ...     provider="qwen3_vl", frames=[Path("f1.png")], prompt="Describe",
    ... )

Raises:
    VLMVideoAnalyzeError: Analysis failed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from obase import ProviderRegistry
from obase.exceptions import ProviderNotFoundError


class VLMVideoAnalyzeError(Exception):
    """VLM video analysis failed."""


async def vlm_video_analyze(
    *,
    provider: str,
    frames: list[Path],
    prompt: str,
    timeout_s: float = 60.0,
) -> str:
    """Analyze video frames using a VLM provider.

    Args:
        provider: VLM provider name (category='vlm').
        frames: List of frame image paths.
        prompt: Analysis prompt/question.
        timeout_s: Timeout in seconds.

    Returns:
        Text analysis result from VLM.

    Raises:
        VLMVideoAnalyzeError: Input validation, provider not found, or VLM failure.

    Example:
        >>> text = await vlm_video_analyze(
        ...     provider="qwen3_vl", frames=[Path("f.png")], prompt="What happens?")
    """
    if not frames:
        raise VLMVideoAnalyzeError("frames must not be empty")
    if not prompt.strip():
        raise VLMVideoAnalyzeError("prompt must not be empty")

    for f in frames:
        if not f.exists():
            raise VLMVideoAnalyzeError(f"Frame not found: {f}")

    try:
        fn = ProviderRegistry.get().vlm(provider)
    except ProviderNotFoundError as exc:
        raise VLMVideoAnalyzeError(f"VLM provider not found: {provider!r}") from exc

    try:
        result: Any = await fn(frames=frames, prompt=prompt, timeout_s=timeout_s)
    except Exception as exc:
        raise VLMVideoAnalyzeError(f"VLM call failed: {exc}") from exc

    if isinstance(result, dict):
        return str(result.get("content", ""))
    return str(result)
