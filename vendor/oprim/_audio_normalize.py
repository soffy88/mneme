"""oprim.audio_normalize — EBU R128 loudness normalization via FFmpeg loudnorm.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.audio_normalize import audio_normalize
    >>> result = asyncio.run(audio_normalize(
    ...     input_path=Path("raw.wav"),
    ...     output_path=Path("normalized.wav"),
    ...     target_lufs=-14.0,
    ... ))

Raises:
    AudioNormalizeError: Normalization failed.
"""

from __future__ import annotations

from pathlib import Path

from obase.ffmpeg import FFmpegError
from obase.ffmpeg import run as ffmpeg_run


class AudioNormalizeError(Exception):
    """Audio normalization failed."""


async def audio_normalize(
    *,
    input_path: Path,
    output_path: Path,
    target_lufs: float = -16.0,
    timeout_s: float = 120.0,
) -> Path:
    """Normalize audio loudness to target LUFS (EBU R128).

    Args:
        input_path: Source audio file.
        output_path: Destination file.
        target_lufs: Target integrated loudness (e.g. -14.0 for YouTube).
        timeout_s: FFmpeg timeout in seconds.

    Returns:
        The output_path on success.

    Raises:
        AudioNormalizeError: On validation failure or FFmpeg error.

    Example:
        >>> await audio_normalize(input_path=Path("in.wav"), output_path=Path("out.wav"))
    """
    if not input_path.exists():
        raise AudioNormalizeError(f"Input file not found: {input_path}")

    args = [
        "-i", str(input_path),
        "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
        str(output_path),
    ]

    try:
        await ffmpeg_run(args=args, timeout_s=timeout_s, expected_output=output_path)
    except FFmpegError as exc:
        raise AudioNormalizeError(f"FFmpeg normalization failed: {exc}") from exc

    return output_path
