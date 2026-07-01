"""oprim.video_quality_metrics — Extract technical video quality metrics via ffprobe.

Example:
    >>> from oprim.video_quality_metrics import video_quality_metrics
    >>> m = await video_quality_metrics(video_path=Path("video.mp4"))

Raises:
    VideoQualityError: Extraction failed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pydantic import BaseModel


class VideoQualityError(Exception):
    """Video quality metrics extraction failed."""


class VideoQualityMetrics(BaseModel):
    """Technical video quality metrics."""

    width: int
    height: int
    duration_s: float
    fps: float
    bitrate_kbps: int
    audio_lufs: float | None = None
    codec_video: str
    codec_audio: str | None = None


async def video_quality_metrics(*, video_path: Path) -> VideoQualityMetrics:
    """Extract technical quality metrics from a video file.

    Args:
        video_path: Path to video file.

    Returns:
        VideoQualityMetrics model.

    Raises:
        VideoQualityError: File not found, ffprobe missing, or parse failure.

    Example:
        >>> m = await video_quality_metrics(video_path=Path("v.mp4"))
    """
    if not video_path.exists():
        raise VideoQualityError(f"Video not found: {video_path}")

    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(video_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
    except FileNotFoundError:
        raise VideoQualityError("ffprobe not found on PATH") from None

    if proc.returncode != 0:
        raise VideoQualityError("ffprobe failed")

    data = json.loads(stdout.decode())
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if not video_stream:
        raise VideoQualityError("No video stream found")

    fps_str = video_stream.get("r_frame_rate", "25/1")
    num, den = fps_str.split("/") if "/" in fps_str else (fps_str, "1")
    fps = float(num) / float(den) if float(den) != 0 else 25.0

    return VideoQualityMetrics(
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        duration_s=float(fmt.get("duration", 0)),
        fps=fps,
        bitrate_kbps=int(float(fmt.get("bit_rate", 0)) / 1000),
        codec_video=video_stream.get("codec_name", "unknown"),
        codec_audio=audio_stream.get("codec_name") if audio_stream else None,
    )
