"""oprim._providers.wan_cloud — Wan 2.6/2.7 Alibaba Cloud API (T2V/I2V).

Moved from hevi service layer per P8.5-B3.5 lesson: duration param removed.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path


class WanCloudError(Exception):
    """Wan cloud API call failed."""


async def invoke(
    *,
    mode: str,
    prompt: str,
    reference_image: Path | None,
    output_path: Path,
    api_key: str,
    base_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
        "video-generation/generation"
    ),
    model: str = "wanx2.6-t2v-turbo",
    poll_interval_s: float = 5.0,
    timeout_s: float = 600.0,
) -> Path:
    """Call Alibaba Cloud Wan 2.6/2.7 for T2V or I2V generation.

    Args:
        mode: "t2v" or "i2v".
        prompt: Text prompt.
        reference_image: Required for i2v; ignored for t2v.
        output_path: Destination file path.
        api_key: DashScope API key (DASHSCOPE_API_KEY).
        base_url: DashScope video generation endpoint.
        model: Wanx model variant.
        poll_interval_s: Seconds between status polls.
        timeout_s: Total timeout for httpx client.

    Returns:
        output_path on success.

    Raises:
        WanCloudError: API error, task failure, or missing video URL.
    """
    import httpx

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }

    input_payload: dict[str, object] = {"prompt": prompt}
    effective_model = model

    if mode == "i2v" and reference_image is not None:
        if not reference_image.exists():
            raise WanCloudError(f"reference_image not found: {reference_image}")
        suffix = reference_image.suffix.lstrip(".") or "png"
        b64 = base64.b64encode(reference_image.read_bytes()).decode()
        input_payload["img_url"] = f"data:image/{suffix};base64,{b64}"
        if "t2v" in effective_model:
            effective_model = effective_model.replace("t2v", "i2v")

    payload = {
        "model": effective_model,
        "input": input_payload,
        "parameters": {},
    }

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(base_url, json=payload, headers=headers)
        if resp.status_code not in (200, 202):
            _raise_api_error("submit", resp)

        submit_data = resp.json()
        task_id: str | None = (submit_data.get("output") or {}).get("task_id")
        if not task_id:
            raise WanCloudError(f"No task_id in submit response: {submit_data}")

        poll_url = (
            "https://dashscope.aliyuncs.com/api/v1/tasks/"
            f"{task_id}"
        )
        poll_headers = {"Authorization": f"Bearer {api_key}"}
        while True:
            await asyncio.sleep(poll_interval_s)
            pr = await client.get(poll_url, headers=poll_headers)
            if pr.status_code != 200:
                _raise_api_error("poll", pr)

            pdata = pr.json()
            task_output = pdata.get("output") or {}
            task_status = task_output.get("task_status", "")

            if task_status == "SUCCEEDED":
                video_url: str | None = task_output.get("video_url")
                if not video_url:
                    raise WanCloudError(f"No video_url in task result: {pdata}")
                dl = await client.get(video_url)
                if dl.status_code != 200:
                    raise WanCloudError(
                        f"Video download failed {dl.status_code}"
                    )
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(dl.content)
                return output_path

            if task_status in ("FAILED", "CANCELLED"):
                code = task_output.get("code", "unknown")
                msg = task_output.get("message", "")
                raise WanCloudError(f"Wan task {task_status}: {code} — {msg}")


def _raise_api_error(stage: str, resp: object) -> None:
    """Extract code+message from response and raise WanCloudError."""
    try:
        data: dict[str, object] = resp.json()  # type: ignore[union-attr]
        code = data.get("code", getattr(resp, "status_code", "?"))
        msg = data.get("message", "")
    except Exception:
        code = getattr(resp, "status_code", "?")
        msg = getattr(resp, "text", "")[:200]
    raise WanCloudError(f"Wan cloud {stage} error {code}: {msg}")
