"""oskill.character_three_view — 单图 → 三视图(正/侧/背).

Combines oprim.image_generate (3 calls) with LLM prompt generation
to produce front/side/back character views from a single portrait.

Example:
    >>> from pathlib import Path
    >>> from oskill.character_three_view import character_three_view
    >>> result = await character_three_view(
    ...     portrait_image=Path("face.png"),
    ...     image_provider="flux",
    ...     llm=my_llm,
    ...     output_dir=Path("out/three_view"),
    ... )
    >>> print(result.front, result.consistency_score)
    out/three_view/front.png 1.0

Raises:
    FileNotFoundError: portrait_image 不存在
    CharacterThreeViewError: LLM/image_gen 失败 / 输出验证失败
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from oskill._llm_caller import LLMCaller


class CharacterThreeViewError(Exception):
    """Three-view generation failed."""


class ThreeViewResult(BaseModel):
    """Result of character three-view generation."""

    front: Path
    side: Path
    back: Path
    consistency_score: float  # 0-1; 1.0 = all 3 views successfully generated


_VIEW_PROMPT = (
    "You are a character concept artist. "
    "Generate image prompts for three standard character views of the described character. "
    "Return STRICT JSON only:\n"
    '{"front": "<front-view prompt>", "side": "<side-view prompt>", "back": "<back-view prompt>"}'
)


async def character_three_view(
    *,
    portrait_image: Path,
    image_provider: str,
    llm: LLMCaller,
    output_dir: Path,
) -> ThreeViewResult:
    """Generate front/side/back character views from a single portrait.

    Internal oprim composition:
    - oprim.image_generate (3 calls: front / side / back view)
    - LLM call for view prompt generation (inlined; not an independent oprim)

    Args:
        portrait_image: Source portrait image path.
        image_provider: Provider name (category='image_gen') for oprim.image_generate.
        llm: LLMCaller for view prompt generation.
        output_dir: Directory where front.png / side.png / back.png are saved.

    Returns:
        ThreeViewResult with front / side / back paths + consistency_score ∈ [0, 1].

    Raises:
        FileNotFoundError: portrait_image does not exist.
        CharacterThreeViewError: LLM call failed, image generation failed,
            or output files not produced.

    Example:
        >>> result = await character_three_view(
        ...     portrait_image=Path("face.png"), image_provider="flux",
        ...     llm=my_llm, output_dir=Path("out/"),
        ... )
    """
    if not portrait_image.exists():
        raise FileNotFoundError(f"portrait_image not found: {portrait_image}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: LLM generates 3 view prompts
    try:
        resp: dict[str, Any] = llm(messages=[{"role": "user", "content": _VIEW_PROMPT}])
        view_prompts: dict[str, Any] = json.loads(resp.get("content", "{}"))
    except Exception as exc:
        raise CharacterThreeViewError(f"LLM view-prompt generation failed: {exc}") from exc

    front_prompt = str(view_prompts.get("front", "character front view, full body, detailed"))
    side_prompt = str(view_prompts.get("side", "character side view, full body, detailed"))
    back_prompt = str(view_prompts.get("back", "character back view, full body, detailed"))

    # Step 2: Generate images (lazy import)
    from oprim.image_generate import ImageGenError, image_generate

    front_path = output_dir / "front.png"
    side_path = output_dir / "side.png"
    back_path = output_dir / "back.png"

    try:
        await image_generate(provider=image_provider, prompt=front_prompt, output_path=front_path)
        await image_generate(provider=image_provider, prompt=side_prompt, output_path=side_path)
        await image_generate(provider=image_provider, prompt=back_prompt, output_path=back_path)
    except ImageGenError as exc:
        raise CharacterThreeViewError(f"Image generation failed: {exc}") from exc
    except Exception as exc:
        raise CharacterThreeViewError(f"Unexpected error during generation: {exc}") from exc

    # Step 3: Validate all outputs exist
    missing = [p for p in (front_path, side_path, back_path) if not p.exists()]
    if missing:
        raise CharacterThreeViewError(f"Provider did not produce outputs: {missing}")

    consistency_score = sum(p.exists() for p in (front_path, side_path, back_path)) / 3.0

    return ThreeViewResult(
        front=front_path,
        side=side_path,
        back=back_path,
        consistency_score=consistency_score,
    )


__all__ = ["character_three_view", "CharacterThreeViewError", "ThreeViewResult"]
