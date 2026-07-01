"""oprim.image_generate — Image generation via provider injection.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.image_generate import image_generate
    >>> result = asyncio.run(image_generate(
    ...     provider="siliconflow", prompt="A sunset over mountains",
    ...     output_path=Path("sunset.png"),
    ... ))

Raises:
    ImageGenError: Generation failed.
    ImageGenRateLimitError: Provider returned 429.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from obase import ProviderRegistry
from obase.exceptions import ProviderNotFoundError


class ImageGenError(Exception):
    """Image generation failed."""


class ImageGenRateLimitError(ImageGenError):
    """Provider returned 429 rate limit."""


async def image_generate(
    *,
    provider: str,
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    output_path: Path,
    seed: int | None = None,
    timeout_s: float = 120.0,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Generate an image using a registered provider.

    Args:
        provider: Provider name in ProviderRegistry (category='image_gen').
        prompt: Text prompt for generation.
        width: Output width in pixels.
        height: Output height in pixels.
        output_path: Destination file path.
        seed: Optional seed for reproducibility.
        timeout_s: Timeout in seconds.
        extra: Provider-specific parameters.

    Returns:
        The output_path on success.

    Raises:
        ImageGenError: Provider not found or generation failed.
        ImageGenRateLimitError: 429 rate limit hit.

    Example:
        >>> await image_generate(provider="siliconflow", prompt="cat", output_path=Path("cat.png"))
    """
    if not prompt:
        raise ImageGenError("prompt must not be empty")

    try:
        gen_fn = ProviderRegistry.get().image_gen(provider)
    except (ProviderNotFoundError, RuntimeError) as exc:
        raise ImageGenError(f"Image gen provider not found: {provider!r}") from exc

    try:
        await gen_fn(
            prompt=prompt,
            width=width,
            height=height,
            output_path=output_path,
            seed=seed,
            timeout_s=timeout_s,
            extra=extra or {},
        )
    except ImageGenRateLimitError:
        raise
    except Exception as exc:
        if "429" in str(exc) or "rate" in str(exc).lower():
            raise ImageGenRateLimitError(f"Rate limited: {exc}") from exc
        raise ImageGenError(f"Image generation failed: {exc}") from exc

    if not output_path.exists():
        raise ImageGenError(f"Provider did not produce output: {output_path}")

    return output_path
