"""oprim.avatar_generate — Digital avatar generation via subprocess provider.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.avatar_generate import avatar_generate
    >>> result = asyncio.run(avatar_generate(
    ...     provider="wav2lip", portrait_image=Path("face.png"),
    ...     audio_path=Path("speech.wav"), output_path=Path("avatar.mp4"),
    ... ))

Raises:
    AvatarGenError: Generation failed.
    AvatarSetupError: Vendor binary not found.
"""

from __future__ import annotations

from pathlib import Path

from obase import ProviderRegistry
from obase.exceptions import ProviderNotFoundError


class AvatarGenError(Exception):
    """Avatar generation failed."""


class AvatarSetupError(AvatarGenError):
    """Vendor binary or dependency not found."""


async def avatar_generate(
    *,
    provider: str,
    portrait_image: Path,
    audio_path: Path,
    output_path: Path,
    fps: int = 25,
    timeout_s: float = 600.0,
) -> Path:
    """Generate a talking-head avatar video.

    Args:
        provider: Avatar provider name in ProviderRegistry (category='avatar').
        portrait_image: Face/portrait image file.
        audio_path: Audio file to lip-sync.
        output_path: Destination video file.
        fps: Output video frame rate.
        timeout_s: Timeout in seconds.

    Returns:
        The output_path on success.

    Raises:
        AvatarGenError: On validation failure or generation error.
        AvatarSetupError: Vendor binary not available.

    Example:
        >>> await avatar_generate(
        ...     provider="wav2lip", portrait_image=Path("face.png"),
        ...     audio_path=Path("audio.wav"), output_path=Path("out.mp4"),
        ... )
    """
    if not portrait_image.exists():
        raise AvatarGenError(f"Portrait image not found: {portrait_image}")

    if not audio_path.exists():
        raise AvatarGenError(f"Audio file not found: {audio_path}")

    # Built-in duix dispatch — local Docker REST, no ProviderRegistry needed
    if provider == "duix":
        from oprim._config import cfg
        from oprim._providers.duix import DuixError
        from oprim._providers.duix import submit_and_poll as _duix_submit

        try:
            return await _duix_submit(
                portrait_image=portrait_image,
                audio_path=audio_path,
                output_path=output_path,
                timeout_s=timeout_s,
                host_data_dir=cfg.get("DUIX_HOST_DATA_DIR"),
                container_data_dir=cfg.get("DUIX_CONTAINER_DATA_DIR", "/code/data"),
            )
        except DuixError as exc:
            raise AvatarGenError(f"Duix generation failed: {exc}") from exc

    try:
        gen_fn = ProviderRegistry.get().generic("avatar", provider)
    except ProviderNotFoundError as exc:
        raise AvatarGenError(f"Avatar provider not found: {provider!r}") from exc

    try:
        await gen_fn(
            portrait_image=portrait_image,
            audio_path=audio_path,
            output_path=output_path,
            fps=fps,
            timeout_s=timeout_s,
        )
    except AvatarSetupError:
        raise
    except Exception as exc:
        if "not found" in str(exc).lower() or "setup" in str(exc).lower():
            raise AvatarSetupError(f"Vendor setup error: {exc}") from exc
        raise AvatarGenError(f"Avatar generation failed: {exc}") from exc

    if not output_path.exists():
        raise AvatarGenError(f"Provider did not produce output: {output_path}")

    return output_path
