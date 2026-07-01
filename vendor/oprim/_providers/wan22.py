"""oprim._providers.wan22 — Wan2.2 local subprocess + DashScope cloud API."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path


class Wan22Error(Exception):
    """Wan2.2 invocation failed."""


class Wan22LocalSetupError(Wan22Error):
    """Vendor binary not found."""


class Wan22CloudError(Wan22Error):
    """Cloud API call failed."""


async def invoke_local(
    *,
    reference_image: Path,
    motion_prompt: str,
    duration_s: float = 5.0,
    output_path: Path,
    vendor_dir: Path,
    timeout_s: float = 600.0,
) -> Path:
    """Run Wan2.2 1.3B locally via subprocess.

    Raises:
        Wan22LocalSetupError: vendor binary missing.
        Wan22Error: subprocess failed or timed out.
    """
    script = vendor_dir / "run.py"
    if not script.exists():
        raise Wan22LocalSetupError(f"Wan2.2 vendor not found: {script}")

    python = vendor_dir / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(shutil.which("python3") or "python3")

    cmd = [
        str(python), str(script),
        "--image", str(reference_image),
        "--prompt", motion_prompt,
        "--duration", str(duration_s),
        "--output", str(output_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        raise Wan22Error(f"Wan2.2 local timed out after {timeout_s}s") from None

    if proc.returncode != 0:
        raise Wan22Error(f"Wan2.2 local exit {proc.returncode}: {stderr.decode()[:300]}")

    if not output_path.exists():
        raise Wan22Error(f"Wan2.2 did not produce output: {output_path}")
    return output_path


async def invoke_cloud(
    *,
    reference_image: Path,
    motion_prompt: str,
    duration_s: float = 5.0,
    output_path: Path,
    api_key: str,
    base_url: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis",
    timeout_s: float = 600.0,
) -> Path:
    """Call DashScope Wan2.2 cloud API.

    Raises:
        Wan22CloudError: API failure or quota exceeded.
    """
    import httpx

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "wanx2.2-i2v-turbo",
        "input": {"image_url": str(reference_image), "prompt": motion_prompt},
        "parameters": {"duration": duration_s},
    }

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(base_url, json=payload, headers=headers)
        if resp.status_code == 429:
            raise Wan22CloudError("Wan2.2 cloud rate limited (429)")
        if resp.status_code != 200:
            raise Wan22CloudError(f"Wan2.2 cloud error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        video_url = data.get("output", {}).get("video_url")
        if not video_url:
            raise Wan22CloudError(f"No video_url in response: {data}")

        dl = await client.get(video_url)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(dl.content)

    return output_path
