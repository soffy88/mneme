"""oprim.audio_video_merge — Merge audio track into video (replacing original).

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.audio_video_merge import audio_video_merge
    >>> result = asyncio.run(audio_video_merge(
    ...     video_path=Path("video.mp4"),
    ...     audio_path=Path("narration.wav"),
    ...     output_path=Path("final.mp4"),
    ... ))

Raises:
    AudioVideoMergeError: Merge failed.
"""

from __future__ import annotations

from pathlib import Path

from obase.ffmpeg import FFmpegError
from obase.ffmpeg import run as ffmpeg_run


class AudioVideoMergeError(Exception):
    """Audio-video merge failed."""


async def audio_video_merge(
    *,
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    audio_codec: str = "aac",
    timeout_s: float = 300.0,
) -> Path:
    """Merge audio into video, replacing the original audio track.

    Args:
        video_path: Source video file.
        audio_path: Audio file to merge in.
        output_path: Destination file.
        audio_codec: Audio codec for output (default: aac).
        timeout_s: FFmpeg timeout in seconds.

    Returns:
        The output_path on success.

    Raises:
        AudioVideoMergeError: On validation failure or FFmpeg error.

    Example:
        >>> await audio_video_merge(
        ...     video_path=Path("v.mp4"), audio_path=Path("a.wav"), output_path=Path("out.mp4")
        ... )
    """
    if not video_path.exists():
        raise AudioVideoMergeError(f"Video file not found: {video_path}")
    if not audio_path.exists():
        raise AudioVideoMergeError(f"Audio file not found: {audio_path}")

    args = [
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", audio_codec,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        str(output_path),
    ]

    try:
        await ffmpeg_run(args=args, timeout_s=timeout_s, expected_output=output_path)
    except FFmpegError as exc:
        raise AudioVideoMergeError(f"FFmpeg merge failed: {exc}") from exc

    return output_path
