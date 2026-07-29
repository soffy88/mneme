"""EchoMimic V2 Drive — 调用侧车生成半身驱动视频。

单次原子操作：音频 + 参考图 → 半身视频。
依赖：httpx（调用侧车 HTTP API）。

降级策略：
  - 侧车不可用 → 返回 None（前端回退 P2 模拟）
  - 超时/错误 → 返回 None + 日志

缓存策略：
  - 按 audio_sha256 + hand_pose_hash 缓存
  - 侧车内置 LRU 缓存；此 oprim 不做二次缓存（避免磁盘膨胀）
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────

ECHO_BASE_URL = os.environ.get("ECHO_BASE_URL", "http://localhost:8081")
ECHO_TIMEOUT_S = float(os.environ.get("ECHO_TIMEOUT_S", "90"))


@dataclass
class EchoDriveResult:
    """EchoMimic 驱动结果。"""

    ok: bool
    video_b64: Optional[str] = None
    video_url: Optional[str] = None
    duration_ms: int = 0
    cached: bool = False
    backend: str = "echomimic_v2"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "video_b64": self.video_b64,
            "video_url": self.video_url,
            "duration_ms": self.duration_ms,
            "cached": self.cached,
            "backend": self.backend,
            "note": self.note,
        }


async def echo_drive(
    *,
    audio_b64: str,
    hand_pose: Optional[dict] = None,
    ref_image_b64: Optional[str] = None,
    emotion: str = "neutral",
    cache_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_s: Optional[float] = None,
) -> EchoDriveResult:
    """调用 EchoMimic V2 侧车生成驱动视频。

    Parameters
    ----------
    audio_b64 : str
        音频 base64（mp3/wav）
    hand_pose : dict, optional
        P2 HandChoreoParams（用于手部引导）
    ref_image_b64 : str, optional
        自定义参考图像 base64（覆盖侧车默认）
    emotion : str
        情绪标签
    cache_key : str, optional
        缓存键（相同音频+参数复用结果）
    base_url : str, optional
        侧车 URL（覆盖环境变量）
    timeout_s : float, optional
        超时秒数（覆盖环境变量）

    Returns
    -------
    EchoDriveResult
        ok=False 表示侧车不可用，前端应回退 P2 模拟
    """
    url = (base_url or ECHO_BASE_URL).rstrip("/")
    timeout = timeout_s or ECHO_TIMEOUT_S

    if not audio_b64 or len(audio_b64) < 100:
        return EchoDriveResult(ok=False, note="audio_b64 too small or empty")

    # 计算缓存键
    if not cache_key:
        audio_hash = hashlib.sha256(audio_b64.encode()).hexdigest()[:12]
        hand_hash = hashlib.sha256(str(hand_pose or {}).encode()).hexdigest()[:8]
        cache_key = f"{audio_hash}_{hand_hash}"

    payload = {
        "audio_b64": audio_b64,
        "hand_pose": hand_pose,
        "ref_image_b64": ref_image_b64,
        "emotion": emotion,
        "cache_key": cache_key,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # 健康检查（快速）
            try:
                health = await client.get(f"{url}/health", timeout=3.0)
                if health.status_code != 200:
                    return EchoDriveResult(
                        ok=False,
                        backend="echomimic_unhealthy",
                        note=f"health check failed: HTTP {health.status_code}",
                    )
            except httpx.TimeoutException:
                return EchoDriveResult(
                    ok=False,
                    backend="echomimic_timeout",
                    note="health check timed out",
                )
            except httpx.ConnectError:
                return EchoDriveResult(
                    ok=False,
                    backend="echomimic_unavailable",
                    note="sidecar not reachable; frontend should use P2 fallback",
                )

            # 生成请求
            resp = await client.post(f"{url}/generate", json=payload)
            if resp.status_code >= 400:
                return EchoDriveResult(
                    ok=False,
                    backend="echomimic_error",
                    note=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )

            data = resp.json()
            if not data.get("ok"):
                return EchoDriveResult(
                    ok=False,
                    backend=data.get("backend", "echomimic_error"),
                    note=data.get("note", "generation failed"),
                )

            return EchoDriveResult(
                ok=True,
                video_b64=data.get("video_b64"),
                video_url=data.get("video_url"),
                duration_ms=int(data.get("duration_ms", 0)),
                cached=bool(data.get("cached", False)),
                backend=data.get("backend", "echomimic_v2"),
                note=data.get("note", ""),
            )

    except httpx.TimeoutException:
        logger.warning("echo_drive: timeout after %ss", timeout)
        return EchoDriveResult(
            ok=False,
            backend="echomimic_timeout",
            note=f"request timed out after {timeout}s",
        )
    except httpx.ConnectError as e:
        logger.warning("echo_drive: connect error: %s", e)
        return EchoDriveResult(
            ok=False,
            backend="echomimic_unavailable",
            note=f"connect error: {e}",
        )
    except Exception as e:
        logger.error("echo_drive: unexpected error: %s", e, exc_info=True)
        return EchoDriveResult(
            ok=False,
            backend="echomimic_exception",
            note=f"{type(e).__name__}: {e}",
        )


async def echo_available(base_url: Optional[str] = None) -> bool:
    """检查侧车是否可用（轻量级健康检查）。"""
    url = (base_url or ECHO_BASE_URL).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{url}/health")
            return resp.status_code == 200
    except Exception:
        return False
