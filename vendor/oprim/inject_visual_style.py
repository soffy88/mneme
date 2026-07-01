"""oprim.inject_visual_style — Inject visual style/lighting into a prompt. SYNC."""
from __future__ import annotations


def inject_visual_style(
    prompt: str,
    *,
    style: str | None = None,
    lighting: str | None = None,
    color_grade: str | None = None,
    camera: str | None = None,
) -> str:
    """Append non-None visual style parameters to a prompt string.

    Args:
        prompt: Base prompt string.
        style: Visual style (e.g. "anime", "photorealistic").
        lighting: Lighting descriptor (e.g. "sunset", "studio").
        color_grade: Color grade (e.g. "warm tones", "desaturated").
        camera: Camera descriptor (e.g. "wide angle", "macro").

    Returns:
        Prompt with style descriptors appended. If all params are None,
        returns the original prompt unchanged.

    Example:
        >>> inject_visual_style("a cat", style="anime", lighting="sunset")
        'a cat, anime style, sunset lighting'
    """
    parts: list[str] = []

    if style is not None:
        parts.append(f"{style} style")
    if lighting is not None:
        parts.append(f"{lighting} lighting")
    if color_grade is not None:
        parts.append(f"{color_grade} color grade")
    if camera is not None:
        parts.append(f"{camera} camera")

    if not parts:
        return prompt

    return prompt + ", " + ", ".join(parts)
