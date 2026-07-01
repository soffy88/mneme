"""oprim.face_animation — Face animation via provider injection.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.face_animation import face_animation
    >>> result = asyncio.run(face_animation(
    ...     provider="wav2lip", portrait_image=Path("face.png"),
    ...     audio_path=Path("speech.wav"), output_path=Path("out.mp4"),
    ... ))

Raises:
    FaceAnimationError: Animation failed.
    FaceAnimationProviderNotFoundError: Provider not registered.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from obase import ProviderRegistry
from obase.exceptions import ProviderNotFoundError


class FaceAnimationError(Exception):
    """Face animation failed."""


class FaceAnimationProviderNotFoundError(FaceAnimationError):
    """Provider not registered."""


async def face_animation(
    *,
    provider: str,
    portrait_image: Path,
    audio_path: Path,
    output_path: Path,
    fps: int = 25,
    extra: dict[str, Any] | None = None,
    timeout_s: float = 600.0,
) -> Path:
    """Animate a portrait with audio using a registered provider.

    Args:
        provider: Provider name (category='face_animation').
        portrait_image: Source portrait image.
        audio_path: Audio file to drive animation.
        output_path: Destination video file.
        fps: Frames per second.
        extra: Provider-specific parameters.
        timeout_s: Timeout in seconds.

    Returns:
        The output_path on success.

    Raises:
        FaceAnimationError: Input validation or animation failed.
        FaceAnimationProviderNotFoundError: Provider not registered.

    Example:
        >>> await face_animation(provider="wav2lip", portrait_image=Path("f.png"),
        ...     audio_path=Path("a.wav"), output_path=Path("o.mp4"))
    """
    if not portrait_image.exists():
        raise FaceAnimationError(f"Portrait not found: {portrait_image}")
    if not audio_path.exists():
        raise FaceAnimationError(f"Audio not found: {audio_path}")

    try:
        fn = ProviderRegistry.get().generic("face_animation", provider)
    except ProviderNotFoundError as exc:
        raise FaceAnimationProviderNotFoundError(
            f"Provider not found: {provider!r}"
        ) from exc

    try:
        await fn(
            portrait_image=portrait_image,
            audio_path=audio_path,
            output_path=output_path,
            fps=fps,
            extra=extra or {},
            timeout_s=timeout_s,
        )
    except (FaceAnimationError, FaceAnimationProviderNotFoundError):
        raise
    except Exception as exc:
        raise FaceAnimationError(f"Animation failed: {exc}") from exc

    if not output_path.exists():
        raise FaceAnimationError(f"Provider did not produce output: {output_path}")
    return output_path
