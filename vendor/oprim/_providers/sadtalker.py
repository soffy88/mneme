"""oprim._providers.sadtalker — SadTalker subprocess wrapper."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path


class SadTalkerError(Exception):
    """SadTalker invocation failed."""


class SadTalkerSetupError(SadTalkerError):
    """Vendor not found."""


async def invoke(
    *,
    portrait_image: Path,
    audio_path: Path,
    output_path: Path,
    vendor_dir: Path,
    fps: int = 25,
    expression_scale: float = 1.0,
    timeout_s: float = 600.0,
) -> Path:
    """Run SadTalker via subprocess.

    Raises:
        SadTalkerSetupError: vendor directory missing.
        SadTalkerError: subprocess failed or timed out.
    """
    script = vendor_dir / "inference.py"
    if not script.exists():
        raise SadTalkerSetupError(f"SadTalker not found: {script}")

    python = vendor_dir / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(shutil.which("python3") or "python3")

    cmd = [
        str(python), str(script),
        "--source_image", str(portrait_image),
        "--driven_audio", str(audio_path),
        "--result_dir", str(output_path.parent),
        "--fps", str(fps),
        "--expression_scale", str(expression_scale),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        raise SadTalkerError(f"SadTalker timed out after {timeout_s}s") from None

    if proc.returncode != 0:
        raise SadTalkerError(f"SadTalker exit {proc.returncode}: {stderr.decode()[:300]}")

    # SadTalker outputs to result_dir; find and rename
    results = list(output_path.parent.glob("*.mp4"))
    if not results:
        raise SadTalkerError("SadTalker produced no output")
    if results[0] != output_path:
        results[0].rename(output_path)

    return output_path
