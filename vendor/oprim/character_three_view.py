"""oprim.character_three_view — Generate front/side/back character reference views via LLM."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel


class ThreeViewResult(BaseModel):
    front_prompt: str
    side_prompt: str
    back_prompt: str
    character_name: str = ""
    style_tags: list[str] = []


class ThreeViewError(Exception):
    """character_three_view generation failed."""


async def character_three_view(
    character_description: str,
    *,
    caller: Any,
    style: str = "",
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 1024,
) -> ThreeViewResult:
    """Generate front/side/back prompts for a character.

    Args:
        character_description: Text describing the character.
        caller: LLM caller (injected).
        style: Optional style tags (e.g. "anime", "realistic").

    Returns:
        ThreeViewResult with prompts for each view angle.
    """
    import json

    system = (
        "You are a character design assistant. Given a character description, "
        "produce front/side/back view prompts for image generation. "
        "Return STRICT JSON: {\"front\": str, \"side\": str, \"back\": str, \"style_tags\": [str]}"
    )
    messages = [
        {
            "role": "user",
            "content": f"Character: {character_description}\nStyle: {style or 'default'}\nGenerate three-view prompts.",
        }
    ]

    try:
        response = await caller(messages=messages, system=system, max_tokens=max_tokens)
        content = response.get("content", [])
        text = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        data = json.loads(text)
        return ThreeViewResult(
            front_prompt=data.get("front", ""),
            side_prompt=data.get("side", ""),
            back_prompt=data.get("back", ""),
            style_tags=data.get("style_tags", []),
        )
    except Exception as exc:
        raise ThreeViewError(f"character_three_view failed: {exc}") from exc
