"""oskill.frame_renderer — Concurrent image generation for shots.

Example:
    >>> from oskill.frame_renderer import frame_renderer
    >>> paths = await frame_renderer(
    ...     references=refs, image_provider="siliconflow", output_dir=Path("frames"),
    ... )

Raises:
    FrameRendererError: Rendering failed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from oskill._schemas import ReferenceDescription


class FrameRendererError(Exception):
    """Frame rendering failed."""


async def frame_renderer(
    *,
    references: list[ReferenceDescription],
    image_provider: str,
    output_dir: Path,
    concurrency: int = 4,
) -> list[Path]:
    """Render reference images concurrently via oprim.image_generate.

    Args:
        references: List of ReferenceDescription with detailed prompts.
        image_provider: Provider name for oprim.image_generate.
        output_dir: Directory to write output images.
        concurrency: Max concurrent image generation tasks.

    Returns:
        List of output image paths.

    Raises:
        FrameRendererError: On empty references or generation failure.

    Example:
        >>> paths = await frame_renderer(
        ...     references=refs, image_provider="mock", output_dir=Path("out"),
        ... )
    """
    if not references:
        raise FrameRendererError("references must not be empty")

    output_dir.mkdir(parents=True, exist_ok=True)

    from oprim.image_generate import image_generate

    sem = asyncio.Semaphore(concurrency)
    results: list[Path] = []

    async def _gen(ref: ReferenceDescription, idx: int) -> Path:
        async with sem:
            out = output_dir / f"{ref.shot_id}_{idx:03d}.png"
            return await image_generate(
                provider=image_provider,
                prompt=ref.detailed_prompt,
                output_path=out,
            )

    tasks = [_gen(ref, i) for i, ref in enumerate(references)]

    for coro in asyncio.as_completed(tasks):
        try:
            path = await coro
            results.append(path)
        except Exception as exc:
            raise FrameRendererError(f"Image generation failed: {exc}") from exc

    return sorted(results)
