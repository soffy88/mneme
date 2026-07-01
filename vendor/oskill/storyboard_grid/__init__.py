"""oskill.storyboard_grid — 单场景 → 宫格分镜图(3×3 或 5×5).

Decomposes a scene via LLM into N sub-shots, generates images for each,
then stitches them into a grid with PIL.

Example:
    >>> from pathlib import Path
    >>> from oskill.storyboard_grid import storyboard_grid
    >>> path = await storyboard_grid(
    ...     scene_description="A dragon attacks a castle at dusk.",
    ...     image_provider="flux", llm=my_llm, grid_size=9,
    ...     output_path=Path("storyboard.png"),
    ... )

Raises:
    ValueError: scene_description 为空
    StoryboardGridError: LLM 输出数不对 / image_gen 失败 / PIL 拼图失败
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from oskill._llm_caller import LLMCaller


class StoryboardGridError(Exception):
    """Storyboard grid generation failed."""


_GRID_PROMPT = (
    "Split the following scene into exactly {n} distinct sub-shots for a storyboard. "
    "Return a STRICT JSON array of exactly {n} short visual description strings. "
    'No markdown. Example: ["shot 1 desc", "shot 2 desc", ...]\n'
    'Scene: "{scene}"'
)


async def storyboard_grid(
    *,
    scene_description: str,
    image_provider: str,
    llm: LLMCaller,
    grid_size: Literal[9, 25] = 9,
    output_path: Path,
) -> Path:
    """Generate a storyboard grid image (3×3 or 5×5) from a scene description.

    Internal oprim composition:
    - oprim.image_generate (grid_size calls: 9 or 25)
    - LLM call for sub-shot description generation (inlined; not an independent oprim)
    - Internal PIL grid stitching (no independent oprim)

    Args:
        scene_description: Scene to storyboard. Must not be empty.
        image_provider: Provider name (category='image_gen') for oprim.image_generate.
        llm: LLMCaller for sub-shot decomposition.
        grid_size: 9 (3×3) or 25 (5×5).
        output_path: Destination path for the stitched grid PNG.

    Returns:
        output_path after writing the grid image.

    Raises:
        ValueError: scene_description is empty.
        StoryboardGridError: LLM returned wrong count, image_gen failed,
            or PIL stitching failed.

    Example:
        >>> path = await storyboard_grid(
        ...     scene_description="Dragon attacks castle.",
        ...     image_provider="flux", llm=my_llm,
        ...     grid_size=9, output_path=Path("sb.png"),
        ... )
    """
    if not scene_description.strip():
        raise ValueError("scene_description must not be empty")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cols = 3 if grid_size == 9 else 5

    # Step 1: LLM splits scene into sub-shot descriptions
    prompt_text = _GRID_PROMPT.format(n=grid_size, scene=scene_description)
    try:
        resp: dict[str, Any] = llm(messages=[{"role": "user", "content": prompt_text}])
        raw = resp.get("content", "[]")
        descriptions: list[Any] = json.loads(raw)
    except Exception as exc:
        raise StoryboardGridError(f"LLM sub-shot generation failed: {exc}") from exc

    if len(descriptions) != grid_size:
        raise StoryboardGridError(
            f"LLM returned {len(descriptions)} descriptions, expected {grid_size}"
        )

    # Step 2: Generate one image per sub-shot (lazy import)
    from oprim.image_generate import ImageGenError, image_generate

    tmp_dir = output_path.parent / f"_stmp_{output_path.stem}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    image_paths: list[Path] = []
    for i, desc in enumerate(descriptions):
        img_path = tmp_dir / f"frame_{i:02d}.png"
        try:
            await image_generate(provider=image_provider, prompt=str(desc), output_path=img_path)
        except ImageGenError as exc:
            raise StoryboardGridError(f"Image gen failed for frame {i}: {exc}") from exc
        except Exception as exc:
            raise StoryboardGridError(f"Unexpected error for frame {i}: {exc}") from exc
        image_paths.append(img_path)

    # Step 3: PIL grid stitch
    try:
        _stitch_grid(image_paths, cols, output_path)
    except Exception as exc:
        raise StoryboardGridError(f"PIL grid stitching failed: {exc}") from exc

    return output_path


def _stitch_grid(image_paths: list[Path], cols: int, output_path: Path) -> None:
    """Stitch images into a rows×cols grid using PIL."""
    from PIL import Image

    imgs = [Image.open(p).convert("RGB") for p in image_paths]
    cell_w, cell_h = imgs[0].size
    rows = (len(imgs) + cols - 1) // cols

    grid = Image.new("RGB", (cols * cell_w, rows * cell_h))
    for idx, img in enumerate(imgs):
        r, c = divmod(idx, cols)
        grid.paste(img, (c * cell_w, r * cell_h))

    grid.save(output_path)


__all__ = ["storyboard_grid", "StoryboardGridError"]
