"""oskill.character_consistency_workflow — 单角色 → 三视图 + 多场景一致性图.

Calls oskill.character_three_view (depth-1) then generates scene variants
via oprim.image_generate for multi-scene character consistency.

Example:
    >>> from pathlib import Path
    >>> from oskill.character_consistency_workflow import character_consistency_workflow
    >>> result = await character_consistency_workflow(
    ...     portrait_image=Path("face.png"),
    ...     scene_descriptions=["hero in forest", "hero in city"],
    ...     llm=my_llm,
    ...     image_provider="flux",
    ...     output_dir=Path("out/"),
    ... )
    >>> print(result.consistency_score, len(result.scene_variants))
    0.875 2

Raises:
    ValueError: scene_descriptions 为空 list
    CharacterConsistencyError: 任一步骤失败
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from oskill._llm_caller import LLMCaller
from oskill.character_three_view import (
    CharacterThreeViewError,
    ThreeViewResult,
    character_three_view,
)


class CharacterConsistencyError(Exception):
    """Character consistency workflow failed."""


class CharacterConsistencyResult(BaseModel):
    """Result of character consistency workflow."""

    three_view: ThreeViewResult
    scene_variants: list[Path]
    consistency_score: float  # 0-1


async def character_consistency_workflow(
    *,
    portrait_image: Path,
    scene_descriptions: list[str],
    llm: LLMCaller,
    image_provider: str,
    output_dir: Path,
) -> CharacterConsistencyResult:
    """Generate three-view character reference + multi-scene consistency variants.

    Internal oskill composition (depth-1):
    - oskill.character_three_view

    Plus oprim composition:
    - oprim.image_generate (one call per scene_description)

    Per v0.9 SPEC oskill 互调约束:
    - 深度=1 (character_three_view 内部不再调 oskill)
    - character_three_view 是 stateless 算法
    - 不循环

    Args:
        portrait_image: Source portrait image for three-view generation.
        scene_descriptions: List of scene descriptions for variant generation. Must not be empty.
        llm: LLMCaller passed through to character_three_view and prompt enrichment.
        image_provider: Provider name (category='image_gen') for oprim.image_generate.
        output_dir: Root directory for all output files.

    Returns:
        CharacterConsistencyResult with three_view, scene_variants, consistency_score ∈ [0, 1].

    Raises:
        ValueError: scene_descriptions is an empty list.
        CharacterConsistencyError: three_view generation or any scene variant failed.

    Example:
        >>> result = await character_consistency_workflow(
        ...     portrait_image=Path("face.png"),
        ...     scene_descriptions=["hero in forest", "hero in city"],
        ...     llm=my_llm, image_provider="flux",
        ...     output_dir=Path("out/"),
        ... )
    """
    if not scene_descriptions:
        raise ValueError("scene_descriptions must not be empty")

    output_dir.mkdir(parents=True, exist_ok=True)
    three_view_dir = output_dir / "three_view"

    # depth-1 oskill call: character_three_view
    try:
        three_view = await character_three_view(
            portrait_image=portrait_image,
            image_provider=image_provider,
            llm=llm,
            output_dir=three_view_dir,
        )
    except FileNotFoundError:
        raise
    except CharacterThreeViewError as exc:
        raise CharacterConsistencyError(f"Three-view generation failed: {exc}") from exc
    except Exception as exc:
        raise CharacterConsistencyError(
            f"Unexpected error in three_view generation: {exc}"
        ) from exc

    # oprim.image_generate for each scene variant (lazy import)
    from oprim.image_generate import ImageGenError, image_generate

    scene_variants: list[Path] = []
    for i, desc in enumerate(scene_descriptions):
        out_path = output_dir / f"variant_{i:02d}.png"
        try:
            await image_generate(provider=image_provider, prompt=desc, output_path=out_path)
        except ImageGenError as exc:
            raise CharacterConsistencyError(f"Scene variant {i} image_gen failed: {exc}") from exc
        except Exception as exc:
            raise CharacterConsistencyError(
                f"Unexpected error for scene variant {i}: {exc}"
            ) from exc
        scene_variants.append(out_path)

    # consistency_score: average of three_view score + scene variant success rate
    variant_success = (
        sum(p.exists() for p in scene_variants) / len(scene_variants) if scene_variants else 0.0
    )
    consistency_score = (three_view.consistency_score + variant_success) / 2.0

    return CharacterConsistencyResult(
        three_view=three_view,
        scene_variants=scene_variants,
        consistency_score=consistency_score,
    )


__all__ = [
    "character_consistency_workflow",
    "CharacterConsistencyError",
    "CharacterConsistencyResult",
]
