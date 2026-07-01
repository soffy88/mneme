"""oprim._providers.musetalk — MuseTalk subprocess wrapper."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Literal


class MuseTalkError(Exception):
    """MuseTalk invocation failed."""


class MuseTalkSetupError(MuseTalkError):
    """Vendor not found."""


async def invoke(
    *,
    portrait_image: Path,
    audio_path: Path,
    output_path: Path,
    vendor_dir: Path,
    fps: int = 25,
    resolution: Literal["256", "512"] = "512",
    timeout_s: float = 600.0,
) -> Path:
    """Run MuseTalk via subprocess.

    Raises:
        MuseTalkSetupError: vendor directory missing.
        MuseTalkError: subprocess failed or timed out.
    """
    script = vendor_dir / "inference.py"
    if not script.exists():
        raise MuseTalkSetupError(f"MuseTalk not found: {script}")

    python = vendor_dir / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(shutil.which("python3") or "python3")

    cmd = [
        str(python), str(script),
        "--source_image", str(portrait_image),
        "--audio", str(audio_path),
        "--output", str(output_path),
        "--fps", str(fps),
        "--resolution", resolution,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        raise MuseTalkError(f"MuseTalk timed out after {timeout_s}s") from None

    if proc.returncode != 0:
        raise MuseTalkError(f"MuseTalk exit {proc.returncode}: {stderr.decode()[:300]}")

    if not output_path.exists():
        raise MuseTalkError(f"MuseTalk did not produce output: {output_path}")
    return output_path
