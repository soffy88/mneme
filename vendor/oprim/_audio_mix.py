"""oprim.audio_mix — Multi-track audio mixing via FFmpeg amix filter.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.audio_mix import audio_mix
    >>> result = asyncio.run(audio_mix(
    ...     inputs=[Path("narration.wav"), Path("bgm.wav")],
    ...     weights=[1.0, 0.3],
    ...     output_path=Path("mixed.wav"),
    ... ))

Raises:
    AudioMixError: Mixing failed (input missing, FFmpeg error, etc.).
"""

from __future__ import annotations

from pathlib import Path

from obase.ffmpeg import FFmpegError
from obase.ffmpeg import run as ffmpeg_run


class AudioMixError(Exception):
    """Audio mixing failed."""


async def audio_mix(
    *,
    inputs: list[Path],
    weights: list[float] | None = None,
    output_path: Path,
    sample_rate: int = 44100,
    timeout_s: float = 120.0,
) -> Path:
    """Mix multiple audio tracks into one output file.

    Args:
        inputs: List of audio file paths to mix.
        weights: Volume weight per track (0.0–1.0). Defaults to 1.0 each.
        output_path: Destination file path.
        sample_rate: Output sample rate in Hz.
        timeout_s: FFmpeg timeout in seconds.

    Returns:
        The output_path on success.

    Raises:
        AudioMixError: On validation failure or FFmpeg error.

    Example:
        >>> await audio_mix(inputs=[Path("a.wav"), Path("b.wav")], output_path=Path("out.wav"))
    """
    if not inputs:
        raise AudioMixError("inputs must not be empty")

    for p in inputs:
        if not p.exists():
            raise AudioMixError(f"Input file not found: {p}")

    if weights is None:
        weights = [1.0] * len(inputs)

    if len(weights) != len(inputs):
        raise AudioMixError("weights length must match inputs length")

    n = len(inputs)
    args: list[str] = []
    for p in inputs:
        args.extend(["-i", str(p)])

    # Build amix filter with volume weights
    volume_filters = [f"[{i}]volume={weights[i]}[a{i}]" for i in range(n)]
    mix_inputs = "".join(f"[a{i}]" for i in range(n))
    filter_complex = ";".join(volume_filters) + f";{mix_inputs}amix=inputs={n}:duration=longest"

    args.extend([
        "-filter_complex", filter_complex,
        "-ar", str(sample_rate),
        str(output_path),
    ])

    try:
        await ffmpeg_run(args=args, timeout_s=timeout_s, expected_output=output_path)
    except FFmpegError as exc:
        raise AudioMixError(f"FFmpeg mixing failed: {exc}") from exc

    return output_path
