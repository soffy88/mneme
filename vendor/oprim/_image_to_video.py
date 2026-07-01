"""oprim.image_to_video — Image-to-video generation via provider injection.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.image_to_video import image_to_video
    >>> result = asyncio.run(image_to_video(
    ...     provider="wan22_local", reference_image=Path("img.png"),
    ...     motion_prompt="slow pan left", output_path=Path("out.mp4"),
    ... ))

Raises:
    ImageToVideoError: Generation failed.
    ImageToVideoProviderNotFoundError: Provider not registered.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from obase import ProviderRegistry
from obase.exceptions import ProviderNotFoundError


class ImageToVideoError(Exception):
    """Image-to-video generation failed."""


class ImageToVideoProviderNotFoundError(ImageToVideoError):
    """Provider not registered."""


async def image_to_video(
    *,
    provider: str,
    reference_image: Path,
    motion_prompt: str,
    duration_s: float = 5.0,
    output_path: Path,
    extra: dict[str, Any] | None = None,
    timeout_s: float = 600.0,
) -> Path:
    """Generate video from a reference image using a registered provider.

    Args:
        provider: Provider name (category='image_to_video').
        reference_image: Source image path.
        motion_prompt: Motion description for animation.
        duration_s: Target duration in seconds.
        output_path: Destination video file.
        extra: Provider-specific parameters.
        timeout_s: Timeout in seconds.

    Returns:
        The output_path on success.

    Raises:
        ImageToVideoError: Input validation or generation failed.
        ImageToVideoProviderNotFoundError: Provider not registered.

    Example:
        >>> await image_to_video(provider="wan22_local", reference_image=Path("x.png"),
        ...     motion_prompt="zoom in", output_path=Path("out.mp4"))
    """
    if not reference_image.exists():
        raise ImageToVideoError(f"Reference image not found: {reference_image}")

    try:
        fn = ProviderRegistry.get().generic("image_to_video", provider)
    except ProviderNotFoundError as exc:
        raise ImageToVideoProviderNotFoundError(
            f"Provider not found: {provider!r}"
        ) from exc

    try:
        await fn(
            reference_image=reference_image,
            motion_prompt=motion_prompt,
            duration_s=duration_s,
            output_path=output_path,
            extra=extra or {},
            timeout_s=timeout_s,
        )
    except (ImageToVideoError, ImageToVideoProviderNotFoundError):
        raise
    except Exception as exc:
        raise ImageToVideoError(f"Generation failed: {exc}") from exc

    if not output_path.exists():
        raise ImageToVideoError(f"Provider did not produce output: {output_path}")
    return output_path
