"""oprim.multi_angle — Generate multi-angle image prompts for a subject."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

_DEFAULT_ANGLES = ["front", "side", "back", "three-quarter"]


class MultiAngleResult(BaseModel):
    angle_prompts: dict[str, str]
    subject_description: str


async def multi_angle(
    subject_description: str,
    *,
    caller: Any,
    angles: list[str] | None = None,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 1024,
) -> MultiAngleResult:
    """Generate image prompts for multiple viewing angles of a subject.

    Args:
        subject_description: Text describing the subject.
        caller: Async LLM caller (injected).
        angles: List of angle names. Defaults to front/side/back/three-quarter.
        model: Model identifier.
        max_tokens: Max tokens for LLM response.

    Returns:
        MultiAngleResult with per-angle prompt strings.

    Raises:
        ValueError: If LLM returns unparseable JSON.
    """
    if angles is None:
        angles = _DEFAULT_ANGLES

    angles_list = ", ".join(angles)
    system = (
        "You are an image prompt engineer. Given a subject description and a list of "
        "viewing angles, generate a distinct image generation prompt for each angle. "
        f"Return STRICT JSON: {{\"angle_prompts\": {{{', '.join(repr(a)+': str' for a in angles)}}}}} "
        "where each value is a detailed image generation prompt."
    )
    messages = [
        {
            "role": "user",
            "content": (
                f"Subject: {subject_description}\n"
                f"Angles: {angles_list}\n"
                "Generate one prompt per angle."
            ),
        }
    ]

    response = await caller(
        messages=messages,
        system=system,
        model=model,
        max_tokens=max_tokens,
    )
    content = response.get("content", [])
    text = "".join(
        b.get("text", "")
        for b in content
        if isinstance(b, dict) and b.get("type") == "text"
    )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"multi_angle: invalid JSON from LLM: {exc}") from exc

    angle_prompts = data.get("angle_prompts", {})
    return MultiAngleResult(
        angle_prompts=angle_prompts,
        subject_description=subject_description,
    )
