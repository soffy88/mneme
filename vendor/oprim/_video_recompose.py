"""oprim.video_recompose — Recompose video aspect ratio (e.g. landscape → portrait).

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.video_recompose import video_recompose
    >>> result = asyncio.run(video_recompose(
    ...     input_path=Path("landscape.mp4"),
    ...     output_path=Path("portrait.mp4"),
    ...     target_width=1080,
    ...     target_height=1920,
    ... ))

Raises:
    VideoRecomposeError: Recomposition failed.
    VideoRecomposeSetupError: ffprobe not available.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Literal

from obase.ffmpeg import FFmpegError
from obase.ffmpeg import run as ffmpeg_run


class VideoRecomposeError(Exception):
    """Video recomposition failed."""


class VideoRecomposeSetupError(Exception):
    """ffprobe binary not found."""


async def video_recompose(
    *,
    input_path: Path,
    output_path: Path,
    target_width: int = 1080,
    target_height: int = 1920,
    method: Literal["center_crop", "smart_crop"] = "center_crop",
    timeout_s: float = 300.0,
) -> Path:
    """Recompose video to target dimensions (e.g. horizontal → vertical).

    Args:
        input_path: Source video file.
        output_path: Destination file.
        target_width: Output width in pixels.
        target_height: Output height in pixels.
        method: 'center_crop' (implemented) or 'smart_crop' (not yet implemented).
        timeout_s: FFmpeg timeout in seconds.

    Returns:
        The output_path on success.

    Raises:
        VideoRecomposeError: On validation failure or FFmpeg error.
        VideoRecomposeSetupError: ffprobe not found.
        NotImplementedError: If method='smart_crop'.

    Example:
        >>> await video_recompose(input_path=Path("in.mp4"), output_path=Path("out.mp4"))
    """
    if method == "smart_crop":
        raise NotImplementedError("smart_crop is not yet implemented")

    if shutil.which("ffprobe") is None:
        raise VideoRecomposeSetupError("ffprobe binary not found on PATH")

    if not input_path.exists():
        raise VideoRecomposeError(f"Input file not found: {input_path}")

    src_w, src_h = await _probe_dimensions(input_path)

    # Check if already matches target aspect
    if src_w == target_width and src_h == target_height:
        raise VideoRecomposeError(
            f"Input already matches target dimensions ({target_width}x{target_height})"
        )

    vf = f"crop={target_width}:{target_height},scale={target_width}:{target_height}"

    args = [
        "-i", str(input_path),
        "-vf", vf,
        "-c:a", "copy",
        str(output_path),
    ]

    try:
        await ffmpeg_run(args=args, timeout_s=timeout_s, expected_output=output_path)
    except FFmpegError as exc:
        raise VideoRecomposeError(f"FFmpeg recompose failed: {exc}") from exc

    return output_path


async def _probe_dimensions(path: Path) -> tuple[int, int]:
    """Get video width and height via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "v:0",
        str(path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        raise VideoRecomposeError(f"ffprobe failed for {path}")

    data = json.loads(stdout)
    streams = data.get("streams", [])
    if not streams:
        raise VideoRecomposeError(f"No video stream found in {path}")

    return int(streams[0]["width"]), int(streams[0]["height"])
