"""oskill.multi_shot_storyboard_workflow — 剧本 → 多镜头分镜 + 宫格预览 + 风格/灯光标记.

Calls oskill.storyboard_grid (depth-1) for grid preview, then generates
per-shot images with optional style/lighting injection via oprim.

Example:
    >>> from pathlib import Path
    >>> from oskill.multi_shot_storyboard_workflow import multi_shot_storyboard_workflow
    >>> from oskill._schemas import Script, Scene
    >>> script = Script(title="Test", description="", scenes=[
    ...     Scene(index=0, narration="", duration_s=5.0, visual_description="hero walks")
    ... ], estimated_duration_s=5.0)
    >>> result = await multi_shot_storyboard_workflow(
    ...     script=script, subjects=[], llm=my_llm,
    ...     image_provider="flux", output_dir=Path("out/"),
    ... )

Raises:
    ValueError: script.scenes 为空
    MultiShotStoryboardError: 任一步骤失败
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from oprim.lighting_control_prompt import LightingType, lighting_control_prompt
from oprim.style_marker_prompt import StyleType, style_marker_prompt
from pydantic import BaseModel  # needed for MultiShotStoryboard

from oskill._llm_caller import LLMCaller
from oskill._schemas import Script, SubjectRef
from oskill.storyboard_grid import StoryboardGridError, storyboard_grid


class MultiShotStoryboardError(Exception):
    """Multi-shot storyboard workflow failed."""


class MultiShotStoryboard(BaseModel):
    """Result of multi-shot storyboard workflow."""

    shots: list[dict[str, Any]]  # each: shot_id / visual_description / motion / subjects_used
    grid_preview: Path | None  # None when grid_size=None


async def multi_shot_storyboard_workflow(
    *,
    script: Script,
    subjects: list[SubjectRef],
    llm: LLMCaller,
    image_provider: str,
    output_dir: Path,
    grid_size: Literal[9, 25] | None = 9,
    style: StyleType | None = None,
    lighting: LightingType | None = None,
) -> MultiShotStoryboard:
    """Generate per-shot storyboard images + optional grid preview with style/lighting injection.

    Internal oskill composition (depth-1):
    - oskill.storyboard_grid (when grid_size is not None)

    Plus oprim composition:
    - oprim.style_marker_prompt (inject style when style is not None)
    - oprim.lighting_control_prompt (inject lighting when lighting is not None)
    - oprim.image_generate (one call per scene shot)

    Per v0.9 SPEC oskill 互调约束:
    - 深度=1 (storyboard_grid 内部不再调 oskill)
    - storyboard_grid 是 stateless 算法
    - 不循环

    Args:
        script: Video script with scenes.
        subjects: Subject/character references (may be empty).
        llm: LLMCaller for prompt enrichment and storyboard_grid sub-calls.
        image_provider: Provider name (category='image_gen') for oprim.image_generate.
        output_dir: Root directory for shot images and grid preview.
        grid_size: 9 (3×3) or 25 (5×5) for grid preview; None = skip grid preview.
        style: Style to inject via oprim.style_marker_prompt; None = no style.
        lighting: Lighting to inject via oprim.lighting_control_prompt; None = no lighting.

    Returns:
        MultiShotStoryboard with shots list + grid_preview path (or None).

    Raises:
        ValueError: script.scenes is empty.
        MultiShotStoryboardError: image_gen or storyboard_grid failed.

    Example:
        >>> result = await multi_shot_storyboard_workflow(
        ...     script=my_script, subjects=[], llm=my_llm,
        ...     image_provider="flux", output_dir=Path("out/"), grid_size=9,
        ... )
    """
    if not script.scenes:
        raise ValueError("script.scenes must not be empty")

    output_dir.mkdir(parents=True, exist_ok=True)

    # lazy import image_generate
    from oprim.image_generate import ImageGenError, image_generate

    subject_names = [s.name for s in subjects]
    shots: list[dict[str, Any]] = []

    for i, scene in enumerate(script.scenes):
        prompt = scene.visual_description

        # inject style and lighting via oprim pure functions
        if style is not None:
            prompt = style_marker_prompt(base_prompt=prompt, style=style)
        if lighting is not None:
            prompt = lighting_control_prompt(base_prompt=prompt, lighting=lighting)

        out_path = output_dir / f"shot_{i:03d}.png"
        try:
            await image_generate(provider=image_provider, prompt=prompt, output_path=out_path)
        except ImageGenError as exc:
            raise MultiShotStoryboardError(f"Shot {i} image_gen failed: {exc}") from exc
        except Exception as exc:
            raise MultiShotStoryboardError(f"Unexpected error for shot {i}: {exc}") from exc

        shots.append(
            {
                "shot_id": f"shot_{i:03d}",
                "visual_description": prompt,
                "motion": scene.narration[:50] if scene.narration else None,
                "subjects_used": subject_names,
            }
        )

    # depth-1 oskill call: storyboard_grid (optional)
    grid_preview: Path | None = None
    if grid_size is not None:
        grid_out = output_dir / "grid_preview.png"
        combined_desc = " | ".join(s.visual_description for s in script.scenes[:5])
        try:
            grid_preview = await storyboard_grid(
                scene_description=combined_desc,
                image_provider=image_provider,
                llm=llm,
                grid_size=grid_size,
                output_path=grid_out,
            )
        except StoryboardGridError as exc:
            raise MultiShotStoryboardError(f"Grid preview generation failed: {exc}") from exc
        except Exception as exc:
            raise MultiShotStoryboardError(f"Unexpected error in grid preview: {exc}") from exc

    return MultiShotStoryboard(shots=shots, grid_preview=grid_preview)


__all__ = [
    "multi_shot_storyboard_workflow",
    "MultiShotStoryboardError",
    "MultiShotStoryboard",
    "SubjectRef",
]
