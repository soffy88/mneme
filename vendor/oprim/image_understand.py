"""oprim.image_understand — VLM image understanding (image → text).

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.image_understand import image_understand
    >>> desc = asyncio.run(image_understand(
    ...     provider="qwen_vl", image_path=Path("photo.jpg"), prompt="Describe this image",
    ... ))

Raises:
    ImageUnderstandError: Understanding failed.
"""

from __future__ import annotations

from pathlib import Path

from obase import ProviderRegistry
from obase.exceptions import ProviderNotFoundError


class ImageUnderstandError(Exception):
    """Image understanding failed."""


async def image_understand(
    *,
    provider: str,
    image_path: Path,
    prompt: str,
    timeout_s: float = 60.0,
) -> str:
    """Understand an image using a VLM provider.

    Args:
        provider: VLM provider name in ProviderRegistry (category='vlm').
        image_path: Path to the image file.
        prompt: Question or instruction for the VLM.
        timeout_s: Timeout in seconds.

    Returns:
        Text description/answer from the VLM.

    Raises:
        ImageUnderstandError: On validation failure or provider error.

    Example:
        >>> text = await image_understand(
        ...     provider="qwen_vl", image_path=Path("img.jpg"), prompt="What is this?"
        ... )
    """
    if not prompt:
        raise ImageUnderstandError("prompt must not be empty")

    if not image_path.exists():
        raise ImageUnderstandError(f"Image file not found: {image_path}")

    try:
        vlm_fn = ProviderRegistry.get().vlm(provider)
    except ProviderNotFoundError as exc:
        raise ImageUnderstandError(f"VLM provider not found: {provider!r}") from exc

    try:
        result: str = await vlm_fn(
            image_path=image_path,
            prompt=prompt,
            timeout_s=timeout_s,
        )
    except Exception as exc:
        raise ImageUnderstandError(f"VLM call failed: {exc}") from exc

    return result
