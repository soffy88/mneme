"""oskill.multi_angle_9 — 单场景 → 9 机位拼图(平视/俯/仰 × 远/中/近).

Combines LLM prompt generation + oprim.image_generate (9 calls) +
internal PIL 3×3 stitching to produce a nine-camera-angle grid.

Example:
    >>> from pathlib import Path
    >>> from oskill.multi_angle_9 import multi_angle_9
    >>> out = await multi_angle_9(
    ...     scene_description="Samurai duel at sunset.",
    ...     image_provider="flux", llm=my_llm,
    ...     output_path=Path("angles.png"),
    ... )

Raises:
    ValueError: scene_description 为空
    MultiAngleError: LLM / image_gen / 拼图失败
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from oskill._llm_caller import LLMCaller


class MultiAngleError(Exception):
    """Multi-angle grid generation failed."""


# 9 camera positions: (view_angle, distance)
_ANGLE_LABELS: list[tuple[str, str]] = [
    ("eye-level", "wide"),
    ("eye-level", "medium"),
    ("eye-level", "close-up"),
    ("high-angle", "wide"),
    ("high-angle", "medium"),
    ("high-angle", "close-up"),
    ("low-angle", "wide"),
    ("low-angle", "medium"),
    ("low-angle", "close-up"),
]

_ANGLE_PROMPT = (
    "You are a cinematographer. For the following scene, generate 9 distinct image prompts "
    "covering all camera angles in this exact order:\n"
    "1. eye-level wide  2. eye-level medium  3. eye-level close-up\n"
    "4. high-angle wide  5. high-angle medium  6. high-angle close-up\n"
    "7. low-angle wide  8. low-angle medium  9. low-angle close-up\n"
    "Return STRICT JSON array of exactly 9 strings. No markdown.\n"
    'Scene: "{scene}"'
)


async def multi_angle_9(
    *,
    scene_description: str,
    image_provider: str,
    llm: LLMCaller,
    output_path: Path,
) -> Path:
    """Generate a 3×3 nine-camera-angle grid image for a scene.

    Internal oprim composition:
    - oprim.image_generate (9 calls: 3 view angles × 3 distances)
    - LLM call for angle-specific prompt generation (inlined; not an independent oprim)
    - Internal PIL 3×3 stitching (no independent oprim)

    9 camera positions:
    - View angles: eye-level / high-angle (俯视) / low-angle (仰视)
    - Distances: wide (远景) / medium (中景) / close-up (近景)

    Args:
        scene_description: Scene to render. Must not be empty.
        image_provider: Provider name (category='image_gen') for oprim.image_generate.
        llm: LLMCaller for angle-prompt generation.
        output_path: Destination path for the 3×3 grid PNG.

    Returns:
        output_path after writing the grid image.

    Raises:
        ValueError: scene_description is empty.
        MultiAngleError: LLM returned wrong count, image_gen failed, or PIL failed.

    Example:
        >>> out = await multi_angle_9(
        ...     scene_description="Samurai duel at sunset.",
        ...     image_provider="flux", llm=my_llm,
        ...     output_path=Path("angles.png"),
        ... )
    """
    if not scene_description.strip():
        raise ValueError("scene_description must not be empty")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Step 1: LLM generates 9 angle-specific prompts
    prompt_text = _ANGLE_PROMPT.format(scene=scene_description)
    try:
        resp: dict[str, Any] = llm(messages=[{"role": "user", "content": prompt_text}])
        angle_prompts: list[Any] = json.loads(resp.get("content", "[]"))
    except Exception as exc:
        raise MultiAngleError(f"LLM angle-prompt generation failed: {exc}") from exc

    if len(angle_prompts) != 9:
        raise MultiAngleError(f"LLM returned {len(angle_prompts)} prompts, expected exactly 9")

    # Step 2: Generate one image per angle (lazy import)
    from oprim.image_generate import ImageGenError, image_generate

    tmp_dir = output_path.parent / f"_atmp_{output_path.stem}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    image_paths: list[Path] = []
    for i, (angle_prompt, (view, dist)) in enumerate(zip(angle_prompts, _ANGLE_LABELS)):
        full_prompt = f"{angle_prompt}, {view} shot, {dist} framing"
        img_path = tmp_dir / f"angle_{i:02d}_{view.replace('-', '_')}_{dist.replace('-', '_')}.png"
        try:
            await image_generate(provider=image_provider, prompt=full_prompt, output_path=img_path)
        except ImageGenError as exc:
            raise MultiAngleError(f"Image gen failed for angle {i} ({view}/{dist}): {exc}") from exc
        except Exception as exc:
            raise MultiAngleError(f"Unexpected error for angle {i}: {exc}") from exc
        image_paths.append(img_path)

    # Step 3: PIL 3×3 stitch
    try:
        _stitch_3x3(image_paths, output_path)
    except Exception as exc:
        raise MultiAngleError(f"PIL grid stitching failed: {exc}") from exc

    return output_path


def _stitch_3x3(image_paths: list[Path], output_path: Path) -> None:
    """Stitch 9 images into a 3×3 grid using PIL."""
    from PIL import Image

    imgs = [Image.open(p).convert("RGB") for p in image_paths]
    cell_w, cell_h = imgs[0].size
    grid = Image.new("RGB", (3 * cell_w, 3 * cell_h))
    for idx, img in enumerate(imgs):
        r, c = divmod(idx, 3)
        grid.paste(img, (c * cell_w, r * cell_h))
    grid.save(output_path)


__all__ = ["multi_angle_9", "MultiAngleError"]
