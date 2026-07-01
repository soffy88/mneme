"""oprim._providers.longcat_avatar — LongCat-Video-Avatar 1.5 vendor wrapper.

LongCat-Video-Avatar 1.5 is an open-source digital human video generation
model by Meituan (74.9 GB, int8-quantized: 37 GB). It uses Whisper-Large
as audio encoder and produces long-form videos with strict identity
consistency, outperforming Wav2Lip / SadTalker / MuseTalk.

Reference:
    https://huggingface.co/meituan-longcat/LongCat-Video-Avatar-1.5

Note:
    - invoke_local: subprocess call to the LongCat inference script.
    - invoke_cloud: TECHNICAL_DEBT — No official Meituan cloud API exists
      as of 2026-05-27. Third-party options (fal.ai, WaveSpeed AI) exist
      but are not officially supported. Implement when official API ships.

Registration:
    This module does NOT auto-register with ProviderRegistry.
    Registration is a service-layer responsibility (hevi/services/).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path


class LongCatAvatarError(Exception):
    """LongCat-Avatar invocation failed."""


class LongCatAvatarSetupError(LongCatAvatarError):
    """Vendor binary or model files missing."""


_LONGCAT_SCRIPT = "inference.py"  # Standard script name in LongCat repo


async def invoke_local(
    *,
    portrait_image: Path,
    audio_path: Path,
    output_path: Path,
    vendor_dir: Path,
    fps: int = 25,
    timeout_s: float = 1800.0,
) -> Path:
    """本地 LongCat-Avatar 1.5 subprocess 调用.

    Calls the LongCat inference script as a subprocess. Requires the model
    files and inference script to be present in vendor_dir.

    Args:
        portrait_image: Input portrait image path.
        audio_path: Driving audio file path.
        output_path: Output video file path.
        vendor_dir: Directory containing the LongCat model and inference script.
        fps: Output video frame rate. Default 25.
        timeout_s: Subprocess timeout in seconds. Default 1800 (30 min).

    Returns:
        output_path on success.

    Raises:
        LongCatAvatarSetupError: vendor_dir missing or inference script not found.
        LongCatAvatarError: Subprocess failed (non-zero exit) or timeout.

    Example:
        >>> result = await invoke_local(
        ...     portrait_image=Path("face.png"), audio_path=Path("speech.wav"),
        ...     output_path=Path("avatar.mp4"), vendor_dir=Path("/models/longcat"),
        ... )
    """
    if not vendor_dir.exists():
        raise LongCatAvatarSetupError(f"vendor_dir not found: {vendor_dir}")

    script_path = vendor_dir / _LONGCAT_SCRIPT
    if not script_path.exists():
        raise LongCatAvatarSetupError(f"LongCat inference script not found: {script_path}")

    if not portrait_image.exists():
        raise LongCatAvatarSetupError(f"Portrait image not found: {portrait_image}")
    if not audio_path.exists():
        raise LongCatAvatarSetupError(f"Audio file not found: {audio_path}")

    cmd = [
        "python",
        str(script_path),
        "--portrait",
        str(portrait_image),
        "--audio",
        str(audio_path),
        "--output",
        str(output_path),
        "--fps",
        str(fps),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(vendor_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except TimeoutError as exc:
            proc.kill()
            await proc.communicate()
            raise LongCatAvatarError(f"LongCat subprocess timed out after {timeout_s}s") from exc

        if proc.returncode != 0:
            raise LongCatAvatarError(
                f"LongCat subprocess exited {proc.returncode}: "
                f"{stderr.decode(errors='replace').strip()}"
            )

    except (LongCatAvatarError, LongCatAvatarSetupError):
        raise
    except Exception as exc:
        raise LongCatAvatarError(f"LongCat subprocess error: {exc}") from exc

    return output_path


async def invoke_cloud(
    *,
    portrait_image: Path,
    audio_path: Path,
    output_path: Path,
    api_key: str,
    base_url: str,
    timeout_s: float = 1800.0,
) -> Path:
    """LongCat 云端 API 调用 (TECHNICAL_DEBT — stub).

    TECHNICAL_DEBT: No official Meituan cloud API for LongCat-Video-Avatar
    exists as of 2026-05-27. Third-party options (fal.ai, WaveSpeed AI)
    provide compatible endpoints but are not officially supported by Meituan.

    Implement this method when an official Meituan cloud API ships, or when
    a specific third-party provider is approved by the project.

    Args:
        portrait_image: Input portrait image path.
        audio_path: Driving audio file path.
        output_path: Output video file path.
        api_key: Cloud API authentication key.
        base_url: Cloud API base URL.
        timeout_s: Request timeout in seconds. Default 1800.

    Returns:
        output_path on success.

    Raises:
        NotImplementedError: Always — no cloud API implemented yet.
        LongCatAvatarError: Cloud API failure (future).

    Example:
        >>> # Not yet implemented — awaiting official Meituan cloud API.
        >>> await invoke_cloud(
        ...     portrait_image=Path("face.png"), audio_path=Path("speech.wav"),
        ...     output_path=Path("avatar.mp4"), api_key="...", base_url="...",
        ... )  # raises NotImplementedError
    """
    # TECHNICAL_DEBT: Implement when official Meituan cloud API ships.
    # Candidate: fal.ai endpoint fal-ai/longcat-single-avatar/image-audio-to-video
    # Candidate: WaveSpeed AI https://api.wavespeed.ai/api/v3/wavespeed-ai/longcat-avatar
    raise NotImplementedError(
        "LongCat cloud API not yet implemented. "
        "No official Meituan cloud API exists as of 2026-05-27. "
        "TECHNICAL_DEBT: Implement when official API ships."
    )


__all__ = [
    "invoke_local",
    "invoke_cloud",
    "LongCatAvatarError",
    "LongCatAvatarSetupError",
]
