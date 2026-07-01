"""oprim.subtitle_burn — Burn subtitles into video (single or dual language).

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.subtitle_burn import subtitle_burn
    >>> result = asyncio.run(subtitle_burn(
    ...     video_path=Path("video.mp4"),
    ...     srt_paths=[Path("zh.srt"), Path("en.srt")],
    ...     output_path=Path("burned.mp4"),
    ... ))

Raises:
    SubtitleBurnError: Burn failed.
"""

from __future__ import annotations

from pathlib import Path

from obase.ffmpeg import FFmpegError
from obase.ffmpeg import run as ffmpeg_run


class SubtitleBurnError(Exception):
    """Subtitle burn failed."""


async def subtitle_burn(
    *,
    video_path: Path,
    srt_paths: list[Path],
    output_path: Path,
    primary_alignment: int = 2,
    secondary_alignment: int = 8,
    timeout_s: float = 300.0,
) -> Path:
    """Burn subtitles into video.

    Args:
        video_path: Source video file.
        srt_paths: 1 SRT = single language, 2 SRTs = dual (primary bottom, secondary top).
        output_path: Destination file.
        primary_alignment: ASS alignment for primary subtitle (2=bottom-center).
        secondary_alignment: ASS alignment for secondary subtitle (8=top-center).
        timeout_s: FFmpeg timeout in seconds.

    Returns:
        The output_path on success.

    Raises:
        SubtitleBurnError: On validation failure or FFmpeg error.

    Example:
        >>> await subtitle_burn(
        ...     video_path=Path("v.mp4"), srt_paths=[Path("sub.srt")],
        ...     output_path=Path("out.mp4"),
        ... )
    """
    if not video_path.exists():
        raise SubtitleBurnError(f"Video file not found: {video_path}")

    if not srt_paths:
        raise SubtitleBurnError("At least one SRT path required")

    if len(srt_paths) > 2:
        raise SubtitleBurnError("Maximum 2 SRT paths supported (primary + secondary)")

    for p in srt_paths:
        if not p.exists():
            raise SubtitleBurnError(f"SRT file not found: {p}")

    if len(srt_paths) == 1:
        vf = _single_sub_filter(srt_paths[0], primary_alignment)
    else:
        vf = _dual_sub_filter(srt_paths[0], srt_paths[1], primary_alignment, secondary_alignment)

    args = [
        "-i", str(video_path),
        "-vf", vf,
        "-c:a", "copy",
        str(output_path),
    ]

    try:
        await ffmpeg_run(args=args, timeout_s=timeout_s, expected_output=output_path)
    except FFmpegError as exc:
        raise SubtitleBurnError(f"FFmpeg subtitle burn failed: {exc}") from exc

    return output_path


def _single_sub_filter(srt: Path, alignment: int) -> str:
    escaped = str(srt).replace(":", r"\:").replace("'", r"\'")
    return f"subtitles='{escaped}':force_style='Alignment={alignment}'"


def _dual_sub_filter(
    primary: Path, secondary: Path, pri_align: int, sec_align: int
) -> str:
    pri_escaped = str(primary).replace(":", r"\:").replace("'", r"\'")
    sec_escaped = str(secondary).replace(":", r"\:").replace("'", r"\'")
    return (
        f"subtitles='{pri_escaped}':force_style='Alignment={pri_align}',"
        f"subtitles='{sec_escaped}':force_style='Alignment={sec_align}'"
    )
