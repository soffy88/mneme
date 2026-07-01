"""P-1: channel_list_videos — list videos from a channel/playlist via yt-dlp."""
from __future__ import annotations

import asyncio
import json
import shutil

from oprim._media_types import VideoMeta


async def channel_list_videos(
    *,
    channel_url: str,
    proxy: str | None = None,
    limit: int | None = None,
    cookies_path: str | Path | None = None,
) -> list[VideoMeta]:
    """List videos from a YouTube channel or playlist using yt-dlp.

    Args:
        channel_url: Channel or playlist URL.
        proxy: Optional HTTP/SOCKS proxy URL passed to yt-dlp --proxy.
        limit: Maximum number of videos to return; uses --playlist-end.
        cookies_path: Optional path to a cookies file in Netscape format.

    Returns:
        List of VideoMeta. Empty list if channel has no public videos.

    Raises:
        ValueError: channel_url is empty.
        RuntimeError: yt-dlp is not installed or yt-dlp subprocess fails.
    """
    if not channel_url.strip():
        raise ValueError("channel_url must not be empty")

    if shutil.which("yt-dlp") is None:
        raise RuntimeError("yt-dlp is not installed or not found in PATH")

    from pathlib import Path
    cookie_args = []
    if cookies_path:
        cookie_file = Path(cookies_path).expanduser()
        if cookie_file.exists():
            cookie_args = ["--cookies", str(cookie_file)]

    cmd = ["yt-dlp", "--flat-playlist", "--dump-json", "--no-warnings"] + cookie_args
    if proxy:
        cmd += ["--proxy", proxy]
    if limit is not None:
        cmd += ["--playlist-end", str(limit)]
    cmd.append(channel_url)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = stderr.decode(errors="replace")
        raise RuntimeError(f"yt-dlp failed (exit {proc.returncode}): {err[:300]}")

    videos: list[VideoMeta] = []
    for line in stdout.decode(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        videos.append(VideoMeta(
            video_id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            duration=float(data.get("duration") or 0.0),
            url=str(data.get("url") or data.get("webpage_url") or ""),
            upload_date=data.get("upload_date"),
            description=data.get("description"),
        ))

    return videos
