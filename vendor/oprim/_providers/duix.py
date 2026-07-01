"""oprim._providers.duix — Duix-Avatar local Docker REST API.

Three-service Docker stack: fun-asr + fish-speech + duix.avatar.
Endpoint: POST 127.0.0.1:8383/easy/submit → poll GET /easy/query?code=<uuid>
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path


class DuixError(Exception):
    """Duix avatar generation failed."""


class DuixSubmitError(DuixError):
    """Submit request to Duix service failed."""


class DuixPollTimeoutError(DuixError):
    """Polling timed out before completion."""


def _map_path(
    p: Path,
    host_dir: str,
    container_dir: str,
    *,
    reverse: bool = False,
) -> str:
    """Translate between host and container-internal paths.

    forward (reverse=False): host_dir prefix → container_dir prefix (for API submit)
    reverse (reverse=True):  container_dir prefix → host_dir prefix (for result retrieval)
    """
    src, dst = (host_dir, container_dir) if not reverse else (container_dir, host_dir)
    s = str(p)
    if src and s.startswith(src):
        return dst.rstrip("/") + "/" + s[len(src):].lstrip("/")
    return s


async def submit_and_poll(
    *,
    portrait_image: Path,
    audio_path: Path,
    output_path: Path,
    base_url: str = "http://127.0.0.1:8383",
    poll_interval_s: float = 3.0,
    timeout_s: float = 300.0,
    host_data_dir: str | None = None,
    container_data_dir: str = "/code/data",
) -> Path:
    """Submit a lip-sync job to Duix-Avatar and poll until complete.

    Args:
        portrait_image: Portrait/video reference file (host path).
        audio_path: Audio file for lip-sync (host path).
        output_path: Destination video file.
        base_url: Duix service base URL.
        poll_interval_s: Seconds between status polls.
        timeout_s: Total timeout.
        host_data_dir: Host-side bind-mount root (e.g. /home/user/duix_data).
            Read from DUIX_HOST_DATA_DIR env/cfg if not supplied.
        container_data_dir: Container-side mount point (default /code/data).
            Read from DUIX_CONTAINER_DATA_DIR env/cfg if not supplied.

    Returns:
        output_path on success.

    Raises:
        DuixSubmitError: submit endpoint returned an error.
        DuixPollTimeoutError: job did not complete within timeout_s.
        DuixError: job failed or output could not be downloaded.
    """
    import httpx
    from oprim._config import cfg

    h_dir = (host_data_dir or cfg.get("DUIX_HOST_DATA_DIR", "")).rstrip("/")
    c_dir = (
        cfg.get("DUIX_CONTAINER_DATA_DIR", "") or container_data_dir
    ).rstrip("/")

    job_code = str(uuid.uuid4())

    # Translate host paths → container paths for the Duix API
    api_audio = _map_path(audio_path, h_dir, c_dir)
    api_portrait = _map_path(portrait_image, h_dir, c_dir)

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        submit_resp = await client.post(
            f"{base_url}/easy/submit",
            json={
                "audio_url": api_audio,
                "video_url": api_portrait,
                "code": job_code,
            },
        )
        if submit_resp.status_code != 200:
            raise DuixSubmitError(
                f"Duix submit error {submit_resp.status_code}: {submit_resp.text[:200]}"
            )
        submit_data = submit_resp.json()
        if submit_data.get("code") != 10000:
            raise DuixSubmitError(
                f"Duix submit rejected: {submit_data}"
            )

        # Poll — status lives in response["data"]["status"] (integer)
        elapsed = 0.0
        while elapsed < timeout_s:
            await asyncio.sleep(poll_interval_s)
            elapsed += poll_interval_s

            query_resp = await client.get(
                f"{base_url}/easy/query",
                params={"code": job_code},
            )
            if query_resp.status_code != 200:
                raise DuixError(
                    f"Duix poll error {query_resp.status_code}: {query_resp.text[:200]}"
                )
            qdata = query_resp.json()
            data = qdata.get("data", {})
            status = data.get("status", "")

            if status in (2, "2", "completed", "success", "done"):
                # Duix returns container-local path in data["result"]
                result_container_str: str | None = (
                    data.get("result")
                    or data.get("video_url")
                    or data.get("url")
                )
                if not result_container_str:
                    raise DuixError(f"No result path in Duix response: {qdata}")

                # Translate container result path → host path for file copy.
                # Duix returns /{uuid}-r.mp4 (no /code/data/temp prefix),
                # so first try direct map, then fall back to {h_dir}/temp/{filename}.
                result_host_str = _map_path(
                    Path(result_container_str), h_dir, c_dir, reverse=True
                )
                result_path = Path(result_host_str)
                if not result_path.exists() and h_dir:
                    result_path = Path(h_dir) / "temp" / result_container_str.lstrip("/")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                if result_path.exists():
                    import shutil
                    shutil.copy2(result_path, output_path)
                elif result_container_str.startswith("http"):
                    dl = await client.get(result_container_str)
                    if dl.status_code != 200:
                        raise DuixError(f"Duix video download failed {dl.status_code}")
                    output_path.write_bytes(dl.content)
                else:
                    raise DuixError(
                        f"Duix result not found: container={result_container_str} host={result_path}"
                    )
                return output_path

            if status in (3, "-1", "failed", "error"):
                raise DuixError(
                    f"Duix job failed: {data.get('msg', data)}"
                )

        raise DuixPollTimeoutError(
            f"Duix job {job_code} did not complete within {timeout_s}s"
        )
