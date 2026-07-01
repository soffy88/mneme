"""oprim.storyboard_grid — Generate a grid of storyboard frames via LLM."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


class StoryboardGridResult(BaseModel):
    shots: list[dict]
    grid_description: str
    total_duration_s: float


async def storyboard_grid(
    script_text: str,
    *,
    caller: Any,
    shots: int = 6,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 2048,
) -> StoryboardGridResult:
    """Generate a storyboard grid from a script via LLM.

    Args:
        script_text: The script or scene description.
        caller: Async LLM caller (injected).
        shots: Number of shots to generate.
        model: Model identifier.
        max_tokens: Max tokens for LLM response.

    Returns:
        StoryboardGridResult with shots list and total duration.

    Raises:
        ValueError: If LLM returns unparseable JSON.
    """
    system = (
        "You are a professional storyboard artist. Given a script, generate a "
        f"storyboard grid with exactly {shots} shots. "
        "Return STRICT JSON with this schema: "
        '{"shots": [{"index": int, "description": str, "duration_s": float, '
        '"camera_angle": str}], "total_duration_s": float}'
    )
    messages = [
        {
            "role": "user",
            "content": (
                f"Script:\n{script_text}\n\n"
                f"Generate a {shots}-shot storyboard grid."
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
        raise ValueError(f"storyboard_grid: invalid JSON from LLM: {exc}") from exc

    shot_list = data.get("shots", [])
    total_dur = float(data.get("total_duration_s", 0.0))
    grid_desc = f"{len(shot_list)}-shot grid, {total_dur}s total"

    return StoryboardGridResult(
        shots=shot_list,
        grid_description=grid_desc,
        total_duration_s=total_dur,
    )
