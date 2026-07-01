"""oprim.ltx2_cloud_generate — LTX-2 cloud video generation via fal.ai.

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from oprim.ltx2_cloud_generate import ltx2_cloud_generate
    >>> out = asyncio.run(ltx2_cloud_generate(
    ...     mode="t2v", prompt="A cat on the moon",
    ...     duration_s=5.0, resolution=(1280, 720), output_path=Path("out.mp4"),
    ... ))

Raises:
    ValueError: Invalid parameters (duration_s > 20, i2v without reference).
    Ltx2CloudError: API failure or missing key.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any, Literal

from oprim._config import cfg


class Ltx2CloudError(Exception):
    """LTX-2 fal.ai generation failed."""


async def ltx2_cloud_generate(
    *,
    config: dict[str, Any] | None = None,
    mode: Literal["t2v", "i2v"],
    prompt: str,
    reference_image: Path | None = None,
    duration_s: float,
    resolution: tuple[int, int],
    audio_enabled: bool = True,
    output_path: Path,
    fps: int = 24,
    bitrate_kbps: int | None = None,
) -> Path:
    """Generate a video clip via LTX-2 on fal.ai cloud.

    Args:
        config: Override dict for FAL_API_KEY / FAL_BASE_URL (falls back to env/cfg).
        mode: "t2v" (text-to-video) or "i2v" (image-to-video).
        prompt: Text prompt.
        reference_image: Required for i2v mode; ignored for t2v.
        duration_s: Clip duration in seconds. Must be ≤ 20 (LTX-2 single-clip limit).
        resolution: (width, height) tuple.
        audio_enabled: Whether to request native audio/video sync.
        output_path: Destination file.

    Returns:
        output_path on success.

    Raises:
        ValueError: duration_s > 20 or i2v with reference_image=None.
        Ltx2CloudError: FAL_API_KEY missing, API error, or download failure.

    Example:
        >>> out = await ltx2_cloud_generate(
        ...     mode="t2v", prompt="sunrise over mountains",
        ...     duration_s=5.0, resolution=(1280, 720), output_path=Path("clip.mp4"),
        ... )
    """
    if duration_s > 20:
        raise ValueError(
            f"duration_s={duration_s} exceeds LTX-2 single-clip limit of 20s"
        )
    if mode == "i2v" and reference_image is None:
        raise ValueError("mode='i2v' requires reference_image")

    cfg_dict = config or {}
    api_key: str = cfg_dict.get("FAL_API_KEY") or cfg.get("FAL_API_KEY", "")  # type: ignore[assignment]
    base_url: str = (
        cfg_dict.get("FAL_BASE_URL")
        or cfg.get("FAL_BASE_URL", "https://fal.run/fal-ai/ltx-video")
    )  # type: ignore[assignment]

    if not api_key:
        raise Ltx2CloudError("FAL_API_KEY not configured")

    payload: dict[str, Any] = {
        "prompt": prompt,
        "duration_seconds": duration_s,
        "width": resolution[0],
        "height": resolution[1],
        "enable_audio": audio_enabled,
        "fps": fps,
    }
    if bitrate_kbps is not None:
        payload["bitrate_kbps"] = bitrate_kbps

    if mode == "i2v" and reference_image is not None:
        if not reference_image.exists():
            raise Ltx2CloudError(f"reference_image not found: {reference_image}")
        suffix = reference_image.suffix.lstrip(".") or "png"
        b64 = base64.b64encode(reference_image.read_bytes()).decode()
        payload["image_url"] = f"data:image/{suffix};base64,{b64}"

    import httpx

    headers = {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(base_url, json=payload, headers=headers)
        if resp.status_code not in (200, 202):
            raise Ltx2CloudError(
                f"fal.ai submit error {resp.status_code}: {resp.text[:300]}"
            )
        data = resp.json()

        # Poll if async job
        request_id: str | None = data.get("request_id")
        if request_id:
            status_url = f"{base_url}/requests/{request_id}/status"
            while True:
                st_resp = await client.get(status_url, headers=headers)
                if st_resp.status_code != 200:
                    raise Ltx2CloudError(
                        f"fal.ai poll {st_resp.status_code}: {st_resp.text[:200]}"
                    )
                st = st_resp.json()
                job_status = st.get("status", "")
                if job_status == "COMPLETED":
                    data = st
                    break
                if job_status in ("FAILED", "CANCELLED"):
                    raise Ltx2CloudError(
                        f"fal.ai job {job_status}: {st.get('error', st)}"
                    )
                await asyncio.sleep(3.0)

        video_url: str | None = (
            (data.get("video") or {}).get("url")
            or data.get("video_url")
            or (data.get("output") or {}).get("video_url")
        )
        if not video_url:
            raise Ltx2CloudError(f"No video URL in fal.ai response: {data}")

        dl = await client.get(video_url)
        if dl.status_code != 200:
            raise Ltx2CloudError(
                f"Video download failed {dl.status_code}: {dl.text[:200]}"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(dl.content)

    if not output_path.exists():
        raise Ltx2CloudError(f"Output file not produced: {output_path}")

    return output_path
