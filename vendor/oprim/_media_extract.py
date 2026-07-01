"""P-2: media_extract — download subtitle text or audio from a video URL."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path

from oprim._media_types import MediaResult


async def media_extract(
    *,
    video_url: str,
    proxy: str | None = None,
    prefer_subtitle: bool = True,
    work_dir: Path,
    cookies_path: str | Path | None = None,
) -> MediaResult:
    """Extract subtitle text or audio from a video URL via yt-dlp.

    When prefer_subtitle=True (default):
    - Detects available subtitles (zh-Hans / zh / en / auto) via yt-dlp --list-subs.
    - If found: downloads subtitle → returns has_subtitle=True, subtitle_text=...
    - If not found: downloads bestaudio → converts to mp3 via yt-dlp -x.

    When prefer_subtitle=False:
    - Always downloads audio.

    Args:
        video_url: URL of the video.
        proxy: Optional proxy URL.
        prefer_subtitle: If True, prefer subtitle text over audio.
        work_dir: Working directory for intermediate files (auto-created).
        cookies_path: Optional path to a cookies file in Netscape format.

    Raises:
        ValueError: video_url is empty.
        RuntimeError: yt-dlp or ffmpeg not installed, or video is private/unavailable.
    """
    if not video_url.strip():
        raise ValueError("video_url must not be empty")

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    _require_yt_dlp()

    yt_dlp_args = []
    if proxy:
        yt_dlp_args += ["--proxy", proxy]
    if cookies_path:
        cookie_file = Path(cookies_path).expanduser()
        if cookie_file.exists():
            yt_dlp_args += ["--cookies", str(cookie_file)]

    # Get video metadata
    info = await _get_video_info(video_url, yt_dlp_args)
    title = str(info.get("title", ""))
    duration = float(info.get("duration") or 0.0)
    metadata = {
        "uploader": info.get("uploader"),
        "upload_date": info.get("upload_date"),
        "description": info.get("description", ""),
    }

    if prefer_subtitle:
        subtitle_text = await _try_download_subtitle(video_url, yt_dlp_args, work_dir)
        if subtitle_text is not None:
            return MediaResult(
                has_subtitle=True,
                subtitle_text=subtitle_text,
                audio_path=None,
                title=title,
                duration=duration,
                metadata=metadata,
            )

    # No subtitle (or prefer_subtitle=False): download audio as mp3
    _require_ffmpeg()
    audio_path = await _download_audio(
        video_url, yt_dlp_args, work_dir, info.get("id", "audio")
    )

    return MediaResult(
        has_subtitle=False,
        subtitle_text=None,
        audio_path=audio_path,
        title=title,
        duration=duration,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_yt_dlp() -> None:
    if shutil.which("yt-dlp") is None:
        raise RuntimeError("yt-dlp is not installed or not found in PATH")


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is not installed or not found in PATH")


async def _get_video_info(url: str, yt_dlp_args: list[str]) -> dict:
    cmd = ["yt-dlp", "--dump-json", "--no-playlist"] + yt_dlp_args + [url]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode(errors="replace")
        if "private" in err.lower() or "unavailable" in err.lower():
            raise RuntimeError(f"Private or unavailable video: {err[:200]}")
        raise RuntimeError(f"yt-dlp info failed (exit {proc.returncode}): {err[:200]}")
    return json.loads(stdout.decode(errors="replace"))


async def _try_download_subtitle(url: str, yt_dlp_args: list[str], work_dir: Path) -> str | None:
    """Check for and download subtitles. Returns cleaned text or None."""
    # Step 1: list available subtitles
    cmd = ["yt-dlp", "--list-subs", "--no-playlist", "--no-warnings"] + yt_dlp_args + [url]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    listing = stdout.decode(errors="replace")

    # Detect preferred language
    target_lang = None
    for lang in ("zh-Hans", "zh", "en", "auto"):
        if lang in listing:
            target_lang = lang
            break

    if target_lang is None:
        return None

    # Step 2: download subtitle
    sub_cmd = [
        "yt-dlp",
        "--write-subs", "--write-auto-subs",
        f"--sub-lang={target_lang}",
        "--convert-subs", "srt",
        "--skip-download", "--no-playlist", "--no-warnings",
        "-o", str(work_dir / "%(id)s.%(ext)s"),
    ] + yt_dlp_args + [url]

    proc = await asyncio.create_subprocess_exec(
        *sub_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    # Find subtitle file
    for pattern in ("*.srt", "*.vtt"):
        for f in sorted(work_dir.glob(pattern)):
            return _clean_subtitle(f.read_text(encoding="utf-8", errors="replace"))

    return None


async def _download_audio(
    url: str, yt_dlp_args: list[str], work_dir: Path, video_id: str
) -> Path:
    """Download best audio and convert to mp3 via yt-dlp -x."""
    out_template = str(work_dir / f"{video_id}.%(ext)s")
    cmd = [
        "yt-dlp", "-f", "bestaudio",
        "-x", "--audio-format", "mp3",
        "--no-playlist", "--no-warnings",
        "-o", out_template,
    ] + yt_dlp_args + [url]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode(errors="replace")
        raise RuntimeError(f"yt-dlp audio download failed: {err[:200]}")

    # Return mp3 path (may not exist yet if conversion is async — find any audio file)
    mp3 = work_dir / f"{video_id}.mp3"
    if mp3.exists():
        return mp3
    for f in sorted(work_dir.glob(f"{video_id}.*")):
        return f
    return mp3  # caller checks existence as needed


def _clean_subtitle(raw: str) -> str:
    """Strip SRT/VTT timestamps, sequence numbers, and headers; return plain text."""
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("WEBVTT") or s.startswith("NOTE") or s.startswith("STYLE"):
            continue
        # Timestamp lines: "00:00:01,000 --> 00:00:03,000" or "00:00:01.000 --> 00:00:03.000"
        if re.match(r"^\d{1,2}:\d{2}", s) and "-->" in s:
            continue
        # Pure sequence numbers (SRT)
        if s.isdigit():
            continue
        lines.append(s)
    return "\n".join(lines)
