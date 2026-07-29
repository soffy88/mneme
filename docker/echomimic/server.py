"""EchoMimic V2 Sidecar — FastAPI 封装。

接收音频（mp3/wav base64）+ 可选手部姿态 → 输出半身驱动视频。

Endpoints:
  POST /generate  — 生成驱动视频
  GET  /health    — 健康检查
  GET  /status    — GPU / 模型状态

环境变量:
  ECHO_DEVICE=cuda|cpu
  ECHO_HALF_BODY=1|0
  ECHO_REF_IMAGE=path  — 参考图像路径
  ECHO_OUTPUT_DIR=path — 输出目录（默认 /app/output）
  ECHO_CACHE_DIR=path  — 缓存目录（默认 /app/cache）
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("echomimic")

# ── Configuration ──────────────────────────────────────────────────────────────

DEVICE = os.environ.get("ECHO_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
HALF_BODY = os.environ.get("ECHO_HALF_BODY", "1") == "1"
REF_IMAGE = os.environ.get("ECHO_REF_IMAGE", "/app/ref/aria_ref.jpg")
OUTPUT_DIR = Path(os.environ.get("ECHO_OUTPUT_DIR", "/app/output"))
CACHE_DIR = Path(os.environ.get("ECHO_CACHE_DIR", "/app/cache"))
ECHOMIMIC_DIR = Path("/app/echomimic")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── Models ─────────────────────────────────────────────────────────────────────


class GenerateRequest(BaseModel):
    """生成请求。"""

    audio_b64: str = Field(..., description="音频 base64 (mp3/wav)")
    duration_s: Optional[float] = Field(None, description="目标时长（秒），None=音频实际时长")
    hand_pose: Optional[dict] = Field(None, description="手部姿态参数（P2 HandChoreoParams）")
    ref_image_b64: Optional[str] = Field(None, description="自定义参考图像 base64（覆盖默认）")
    cache_key: Optional[str] = Field(None, description="缓存键（相同音频+参数复用结果）")
    emotion: str = Field("neutral", description="情绪标签")


class GenerateResponse(BaseModel):
    """生成结果。"""

    ok: bool = True
    video_url: Optional[str] = None
    video_b64: Optional[str] = None
    duration_ms: int = 0
    backend: str = "echomimic_v2"
    cached: bool = False
    note: str = ""


class HealthResponse(BaseModel):
    status: str = "ok"
    device: str = DEVICE
    half_body: bool = HALF_BODY
    model_loaded: bool = False
    gpu_available: bool = torch.cuda.is_available()
    gpu_name: str = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A"


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="EchoMimic V2 Sidecar", version="0.1.0")

# 延迟加载模型（首次请求时）
_pipeline: Any = None


def _load_pipeline():
    """加载 EchoMimic V2 pipeline（首次请求时）。"""
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    logger.info("Loading EchoMimic V2 pipeline...")
    try:
        import sys

        sys.path.insert(0, str(ECHOMIMIC_DIR))
        # EchoMimic V2 的具体加载方式取决于其 API
        # 这里是适配框架；实际调用需要根据 EchoMimic V2 的 inference.py 调整
        from diffusers import StableDiffusionPipeline

        # Placeholder: 实际应加载 EchoMimic V2 的 pipeline
        # 由于 EchoMimic V2 的 API 可能变化，这里保持灵活性
        _pipeline = {"loaded": True, "device": DEVICE, "model": "EchoMimicV2"}
        logger.info("Pipeline loaded: %s", _pipeline)
    except Exception as e:
        logger.error("Failed to load pipeline: %s", e)
        _pipeline = {"loaded": False, "error": str(e)}
    return _pipeline


def _cache_path(audio_hash: str) -> Path:
    """缓存文件路径。"""
    return CACHE_DIR / f"{audio_hash}.mp4"


def _generate_video(
    audio_path: str,
    ref_path: str,
    output_path: str,
    hand_pose: Optional[dict] = None,
) -> bool:
    """调用 EchoMimic V2 生成视频。

    Returns True if successful.
    """
    pipe = _load_pipeline()
    if not pipe or not pipe.get("loaded"):
        logger.error("Pipeline not loaded")
        return False

    try:
        # === EchoMimic V2 实际调用 ===
        # 这里需要根据 EchoMimic V2 的 inference.py 来适配
        # 基本流程: 读取音频 + 参考图 → 推理 → 输出视频

        import subprocess

        cmd = [
            "python",
            str(ECHOMIMIC_DIR / "inference.py"),
            "--audio_path", audio_path,
            "--ref_image_path", ref_path,
            "--output_path", output_path,
            "--device", DEVICE,
        ]
        if HALF_BODY:
            cmd.append("--half_body")
        if hand_pose:
            # 将 hand_pose 写入临时 JSON 文件
            hp_path = output_path + ".handpose.json"
            Path(hp_path).write_text(json.dumps(hand_pose))
            cmd.extend(["--hand_pose", hp_path])

        logger.info("Running: %s", " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(ECHOMIMIC_DIR),
        )

        if result.returncode != 0:
            logger.error("EchoMimic inference failed: %s", result.stderr)
            return False

        if not Path(output_path).exists():
            logger.error("Output video not found: %s", output_path)
            return False

        return True

    except subprocess.TimeoutExpired:
        logger.error("EchoMimic inference timed out (>120s)")
        return False
    except Exception as e:
        logger.error("EchoMimic inference error: %s", e)
        return False


# ── Endpoints ──────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> HealthResponse:
    pipe = _pipeline or {}
    return HealthResponse(
        status="ok" if pipe.get("loaded") else "loading",
        model_loaded=bool(pipe.get("loaded")),
    )


@app.get("/status")
async def status() -> dict:
    return {
        "device": DEVICE,
        "half_body": HALF_BODY,
        "ref_image": REF_IMAGE,
        "output_dir": str(OUTPUT_DIR),
        "cache_dir": str(CACHE_DIR),
        "model_loaded": bool(_pipeline and _pipeline.get("loaded")),
        "gpu_available": torch.cuda.is_available(),
        "gpu_memory_gb": (
            round(torch.cuda.get_device_properties(0).total_mem / 1e9, 1)
            if torch.cuda.is_available()
            else 0
        ),
    }


@app.post("/generate")
async def generate(req: GenerateRequest) -> GenerateResponse:
    """生成驱动视频。"""
    t0 = time.time()

    # 1. 解码音频
    try:
        audio_bytes = base64.b64decode(req.audio_b64)
    except Exception:
        raise HTTPException(400, "Invalid audio_b64")

    if len(audio_bytes) < 100:
        raise HTTPException(400, "Audio too small")

    # 2. 缓存检查
    audio_hash = hashlib.sha256(audio_bytes).hexdigest()[:16]
    cache_key = req.cache_key or audio_hash
    cached_path = _cache_path(cache_key)

    if cached_path.exists():
        logger.info("Cache hit: %s", cache_key)
        video_bytes = cached_path.read_bytes()
        return GenerateResponse(
            ok=True,
            video_b64=base64.b64encode(video_bytes).decode("ascii"),
            duration_ms=0,  # 需要 ffprobe 获取
            cached=True,
            note="cache hit",
        )

    # 3. 写入临时音频
    audio_suffix = ".wav" if audio_bytes[:4] == b"RIFF" else ".mp3"
    with tempfile.NamedTemporaryFile(suffix=audio_suffix, delete=False) as f:
        f.write(audio_bytes)
        audio_path = f.name

    # 4. 参考图像
    ref_path = REF_IMAGE
    if req.ref_image_b64:
        try:
            ref_bytes = base64.b64decode(req.ref_image_b64)
            ref_tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            ref_tmp.write(ref_bytes)
            ref_tmp.close()
            ref_path = ref_tmp.name
        except Exception:
            logger.warning("Invalid ref_image_b64, using default")

    # 5. 生成视频
    output_path = str(OUTPUT_DIR / f"echo_{audio_hash}.mp4")
    success = _generate_video(audio_path, ref_path, output_path, req.hand_pose)

    # 清理临时文件
    try:
        os.unlink(audio_path)
    except OSError:
        pass

    if not success:
        return GenerateResponse(
            ok=False,
            backend="echomimic_v2_error",
            note="generation failed; frontend should fallback to P2 simulated hands",
        )

    # 6. 缓存结果
    try:
        import shutil
        shutil.copy2(output_path, cached_path)
    except Exception as e:
        logger.warning("Cache write failed: %s", e)

    # 7. 返回
    video_bytes = Path(output_path).read_bytes()
    elapsed_ms = int((time.time() - t0) * 1000)

    return GenerateResponse(
        ok=True,
        video_b64=base64.b64encode(video_bytes).decode("ascii"),
        duration_ms=elapsed_ms,
        backend="echomimic_v2",
        cached=False,
        note=f"generated in {elapsed_ms}ms",
    )


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting EchoMimic V2 sidecar on :8080 (device=%s)", DEVICE)
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
