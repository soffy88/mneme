"""oskill.subtitle_generator — Generate SRT/ASS from shot plans.

Example:
    >>> from oskill.subtitle_generator import subtitle_generator
    >>> path = subtitle_generator(shots=plans, output_path=Path("sub.srt"))

Raises:
    SubtitleGeneratorError: Generation failed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from oskill._schemas import ShotPlan


class SubtitleGeneratorError(Exception):
    """Subtitle generation failed."""


def subtitle_generator(
    *,
    shots: list[ShotPlan],
    output_path: Path,
    format: Literal["srt", "ass"] = "srt",
) -> Path:
    """Generate subtitle file from shot plans.

    Args:
        shots: List of ShotPlan with tts_text and duration_s.
        output_path: Destination subtitle file.
        format: Output format ('srt' or 'ass').

    Returns:
        The output_path on success.

    Raises:
        SubtitleGeneratorError: On empty shots.

    Example:
        >>> path = subtitle_generator(shots=plans, output_path=Path("sub.srt"))
    """
    if not shots:
        raise SubtitleGeneratorError("shots must not be empty")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if format == "srt":
        _write_srt(shots, output_path)
    else:
        _write_ass(shots, output_path)

    return output_path


def _format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _write_srt(shots: list[ShotPlan], path: Path) -> None:
    offset = 0.0
    with path.open("w", encoding="utf-8") as f:
        for idx, shot in enumerate(shots, 1):
            start = _format_srt_time(offset)
            end = _format_srt_time(offset + shot.duration_s)
            f.write(f"{idx}\n{start} --> {end}\n{shot.tts_text}\n\n")
            offset += shot.duration_s


def _write_ass(shots: list[ShotPlan], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write("[Script Info]\nTitle: Generated\nScriptType: v4.00+\n\n")
        f.write("[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour\n")
        f.write("Style: Default,Arial,20,&H00FFFFFF\n\n")
        f.write("[Events]\nFormat: Layer,Start,End,Style,Name,Text\n")
        offset = 0.0
        for shot in shots:
            start = _format_ass_time(offset)
            end = _format_ass_time(offset + shot.duration_s)
            f.write(f"Dialogue: 0,{start},{end},Default,,{shot.tts_text}\n")
            offset += shot.duration_s
