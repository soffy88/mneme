"""oprim.render_html_to_mp4 — Headless HTML/CSS/GSAP → MP4.

Rendering pipeline:
  1. validate_html guard (when validate=True)
  2. Write HTML to temp file
  3. Headless browser captures frames at `fps` for `duration_s` seconds
  4. ffmpeg encodes frames → H.264 MP4 (compatible with video_concat)

Local-only, zero cost. Output codec matches video_generate for assembly compatibility.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from oprim._validate_html import validate_html
from obase.ffmpeg import run as ffmpeg_run


class RenderHtmlError(Exception):
    """HTML render failed (validation rejection or rendering error)."""


async def render_html_to_mp4(
    *,
    html: str,
    output_path: Path,
    duration_s: float,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    validate: bool = True,
    timeout_s: float = 120.0,
) -> Path:
    """Render HTML/CSS/GSAP animation to MP4.

    validate=True (default) runs validate_html first; raises RenderHtmlError
    on any violation to prevent unsafe content from being encoded.

    Output is H.264/AAC in MP4 container — same codec as video_generate,
    so output is directly assemblable by video_concat.

    Args:
        html: Full HTML document string (animations driven by CSS/GSAP).
        output_path: Destination MP4 file.
        duration_s: Clip duration in seconds.
        width, height: Output resolution (default 1920×1080).
        fps: Frames per second (default 30).
        validate: Run validate_html safety check before rendering.
        timeout_s: Hard timeout for the full render pipeline.

    Returns:
        output_path on success.

    Raises:
        RenderHtmlError: Safety validation failed or rendering error.
    """
    if validate:
        val = validate_html(html=html)
        if not val.is_safe:
            raise RenderHtmlError(
                f"HTML validation failed — rendering blocked. "
                f"Violations: {val.violations}"
            )

    if not html.strip():
        raise RenderHtmlError("Cannot render empty HTML")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        html_file = tmp / "animation.html"
        html_file.write_text(html, encoding="utf-8")
        frames_dir = tmp / "frames"
        frames_dir.mkdir()

        await _capture_html_frames(
            html_path=html_file,
            frames_dir=frames_dir,
            duration_s=duration_s,
            fps=fps,
            width=width,
            height=height,
            timeout_s=timeout_s,
        )

        await _encode_frames_to_mp4(
            frames_dir=frames_dir,
            output_path=output_path,
            fps=fps,
            width=width,
            height=height,
            timeout_s=timeout_s,
        )

    return output_path


async def _capture_html_frames(
    *,
    html_path: Path,
    frames_dir: Path,
    duration_s: float,
    fps: int,
    width: int,
    height: int,
    timeout_s: float,
) -> None:
    """Capture per-frame screenshots via headless Chromium.

    Separated for mockability. Tests patch this function; production
    calls chromium --headless via subprocess advancing GSAP timeline.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RenderHtmlError(
            "playwright is required for HTML rendering. "
            "Install with: pip install playwright && playwright install chromium"
        ) from exc

    frame_count = max(1, int(duration_s * fps))
    frame_step_ms = 1000.0 / fps

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": width, "height": height})
        await page.goto(f"file://{html_path.resolve()}", timeout=int(timeout_s * 1000))

        for i in range(frame_count):
            t_ms = i * frame_step_ms
            await page.evaluate(f"window._renderFrame && window._renderFrame({t_ms})")
            await page.screenshot(
                path=str(frames_dir / f"frame_{i:06d}.png"),
                clip={"x": 0, "y": 0, "width": width, "height": height},
            )

        await browser.close()


async def _encode_frames_to_mp4(
    *,
    frames_dir: Path,
    output_path: Path,
    fps: int,
    width: int,
    height: int,
    timeout_s: float,
) -> None:
    """Encode captured PNG frames to H.264 MP4 via ffmpeg."""
    args = [
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%06d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-vf", f"scale={width}:{height}",
        "-movflags", "+faststart",
        str(output_path),
    ]
    await ffmpeg_run(args=args, timeout_s=timeout_s, expected_output=output_path)
