"""oprim.video_concat — Concatenate multiple video files.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.video_concat import video_concat
    >>> result = asyncio.run(video_concat(
    ...     inputs=[Path("part1.mp4"), Path("part2.mp4")],
    ...     output_path=Path("full.mp4"),
    ... ))

Raises:
    VideoConcatError: Concatenation failed.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Literal

from obase.ffmpeg import FFmpegError
from obase.ffmpeg import run as ffmpeg_run


class VideoConcatError(Exception):
    """Video concatenation failed."""


async def video_concat(
    *,
    inputs: list[Path],
    output_path: Path,
    method: Literal["concat_filter", "concat_demuxer"] = "concat_demuxer",
    timeout_s: float = 600.0,
    tail_frame_handling: bool = False,
    trim_lead_frames: int = 0,
    transitions: list[dict] | None = None,
) -> Path:
    """Concatenate multiple video files into one.

    Args:
        inputs: List of video file paths (≥2 required).
        output_path: Destination file.
        method: 'concat_demuxer' (fast, same codec) or 'concat_filter' (re-encode).
        timeout_s: FFmpeg timeout in seconds.
        tail_frame_handling: When True, force re-encode to flush tail frames before
            the next clip (prevents freeze artifacts from codec B-frame flush).
        trim_lead_frames: Number of leading frames to trim from each clip after
            the first (0 = no trimming). Use 1-2 to remove stutter artifacts.
        transitions: Optional list of transition specs applied between clips:
            [{type: "hard"|"dissolve"|"flash", duration_s: float}, ...].
            Length must be len(inputs)-1. None = hard cut (default).
            "dissolve" → cross-dissolve (xfade=fade), "flash" → flash-to-white
            (xfade=fadewhite), "hard" → plain cut. Overlapping transitions probe
            clip durations (ffprobe) to place each xfade and keep A/V in sync.

    Returns:
        The output_path on success.

    Raises:
        VideoConcatError: On validation failure or FFmpeg error.

    Example:
        >>> await video_concat(inputs=[Path("a.mp4"), Path("b.mp4")], output_path=Path("out.mp4"))
    """
    if len(inputs) < 2:
        raise VideoConcatError("At least 2 input videos required")

    for p in inputs:
        if not p.exists():
            raise VideoConcatError(f"Input file not found: {p}")

    if transitions is not None and len(transitions) != len(inputs) - 1:
        raise VideoConcatError(
            f"transitions length ({len(transitions)}) must equal len(inputs)-1 "
            f"({len(inputs) - 1})"
        )

    # When advanced features are requested, force re-encode via concat_filter.
    # Default (all False/0/None) falls through to the caller-specified method
    # with identical behaviour to previous versions.
    needs_reencode = tail_frame_handling or trim_lead_frames > 0 or transitions is not None
    effective_method = "concat_filter" if needs_reencode else method

    try:
        if effective_method == "concat_demuxer":
            await _concat_demuxer(inputs, output_path, timeout_s)
        else:
            await _concat_filter(
                inputs, output_path, timeout_s,
                trim_lead_frames=trim_lead_frames,
                transitions=transitions or [],
            )
    except FFmpegError as exc:
        raise VideoConcatError(f"FFmpeg concat failed: {exc}") from exc

    return output_path


async def _concat_demuxer(inputs: list[Path], output_path: Path, timeout_s: float) -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for p in inputs:
            f.write(f"file '{p.resolve()}'\n")
        list_path = Path(f.name)

    try:
        args = [
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_path),
            "-c", "copy",
            str(output_path),
        ]
        await ffmpeg_run(args=args, timeout_s=timeout_s, expected_output=output_path)
    finally:
        list_path.unlink(missing_ok=True)


# Map a transition spec type → ffmpeg xfade transition kind.
_XFADE_KIND = {"dissolve": "fade", "flash": "fadewhite"}

# Assumed fps for converting trim_lead_frames → an audio-trim offset (seconds).
_ASSUMED_FPS = 30.0


async def _concat_filter(
    inputs: list[Path],
    output_path: Path,
    timeout_s: float,
    trim_lead_frames: int = 0,
    transitions: list[dict] | None = None,
) -> None:
    if transitions:
        await _concat_with_transitions(
            inputs, output_path, timeout_s,
            trim_lead_frames=trim_lead_frames,
            transitions=transitions,
        )
        return

    n = len(inputs)
    args: list[str] = []
    for p in inputs:
        args.extend(["-i", str(p)])

    # Build per-stream trim filters for lead-frame removal (clips 1..n-1)
    filter_parts: list[str] = []
    for i in range(n):
        if i > 0 and trim_lead_frames > 0:
            filter_parts.append(f"[{i}:v]trim=start_frame={trim_lead_frames}[v{i}t];")
            filter_parts.append(f"[{i}:a]atrim=start={trim_lead_frames / _ASSUMED_FPS:.4f}[a{i}t];")
            v_label, a_label = f"[v{i}t]", f"[a{i}t]"
        else:
            v_label, a_label = f"[{i}:v]", f"[{i}:a]"
        filter_parts.append(f"{v_label}{a_label}")

    concat_inputs = "".join(filter_parts)
    filter_complex = f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]"

    args.extend([
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ])
    await ffmpeg_run(args=args, timeout_s=timeout_s, expected_output=output_path)


async def _concat_with_transitions(
    inputs: list[Path],
    output_path: Path,
    timeout_s: float,
    trim_lead_frames: int,
    transitions: list[dict],
) -> None:
    """Concatenate clips applying a per-junction transition (fold chain).

    Junction i (between clip i and i+1) honours ``transitions[i]``:
      - "dissolve" → xfade=fade        (cross-dissolve)
      - "flash"    → xfade=fadewhite   (flash-to-white)
      - "hard"     → plain concat cut  (no overlap)

    xfade junctions overlap clips by ``duration_s``, so the running timeline
    position is needed to compute each xfade ``offset``. Absolute clip
    durations are probed via ffprobe (only when an overlapping junction
    exists). Audio mirrors video — acrossfade for overlapping junctions,
    concat for hard cuts — keeping A/V in sync as the timeline shortens.
    """
    n = len(inputs)

    needs_durations = any(
        spec.get("type", "hard") != "hard" and float(spec.get("duration_s", 0.0)) > 0.0
        for spec in transitions
    )
    durations = await _probe_durations(inputs) if needs_durations else [0.0] * n

    args: list[str] = []
    for p in inputs:
        args.extend(["-i", str(p)])

    parts: list[str] = []
    base_v: list[str] = []
    base_a: list[str] = []

    # Normalise each input: optional lead-frame trim, fixed pixfmt, and a PTS
    # reset (xfade/concat require monotonic timestamps starting at 0).
    for i in range(n):
        vf: list[str] = []
        af: list[str] = []
        if i > 0 and trim_lead_frames > 0:
            vf.append(f"trim=start_frame={trim_lead_frames}")
            af.append(f"atrim=start={trim_lead_frames / _ASSUMED_FPS:.4f}")
        vf.extend(["format=yuv420p", "setpts=PTS-STARTPTS"])
        af.append("asetpts=PTS-STARTPTS")
        parts.append(f"[{i}:v]{','.join(vf)}[bv{i}];")
        parts.append(f"[{i}:a]{','.join(af)}[ba{i}];")
        base_v.append(f"[bv{i}]")
        base_a.append(f"[ba{i}]")

    v_acc, a_acc = base_v[0], base_a[0]
    running = durations[0]

    for i in range(1, n):
        spec = transitions[i - 1]
        ttype = spec.get("type", "hard")
        dur = float(spec.get("duration_s", 0.0))
        v_out, a_out = f"[vc{i}]", f"[ac{i}]"

        if ttype == "hard" or dur <= 0.0:
            parts.append(f"{v_acc}{base_v[i]}concat=n=2:v=1:a=0{v_out};")
            parts.append(f"{a_acc}{base_a[i]}concat=n=2:v=0:a=1{a_out};")
            running += durations[i]
        else:
            kind = _XFADE_KIND.get(ttype, "fade")
            offset = max(0.0, running - dur)
            parts.append(
                f"{v_acc}{base_v[i]}xfade=transition={kind}:duration={dur:.4f}:offset={offset:.4f}{v_out};"
            )
            parts.append(f"{a_acc}{base_a[i]}acrossfade=d={dur:.4f}{a_out};")
            running += durations[i] - dur

        v_acc, a_acc = v_out, a_out

    filter_complex = "".join(parts).rstrip(";")

    args.extend([
        "-filter_complex", filter_complex,
        "-map", v_acc,
        "-map", a_acc,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(output_path),
    ])
    await ffmpeg_run(args=args, timeout_s=timeout_s, expected_output=output_path)


async def _probe_durations(inputs: list[Path]) -> list[float]:
    """Return each input's container duration in seconds via ffprobe."""
    durations: list[float] = []
    for p in inputs:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", str(p),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
        except FileNotFoundError as exc:
            raise VideoConcatError("ffprobe not found on PATH") from exc
        if proc.returncode != 0:
            raise VideoConcatError(f"ffprobe failed for {p}")
        try:
            durations.append(float(json.loads(stdout.decode())["format"]["duration"]))
        except (KeyError, ValueError) as exc:
            raise VideoConcatError(f"Could not parse duration for {p}") from exc
    return durations
