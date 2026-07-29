"""EchoMimic V2 Sidecar — Native (non-Docker) FastAPI 封装。

从 docker/echomimic/server.py 适配为本地运行版本。
路径默认使用 .echo/ 子目录。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

# 添加 vendor 到路径（本地运行时需要）
_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root))

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("echomimic")

# ── Configuration ──────────────────────────────────────────────────────────────

_ECHO_DIR = Path(__file__).resolve().parent

DEVICE = os.environ.get("ECHO_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
HALF_BODY = os.environ.get("ECHO_HALF_BODY", "1") == "1"
REF_IMAGE = os.environ.get("ECHO_REF_IMAGE", str(_ECHO_DIR / "ref" / "aria_ref.jpg"))
OUTPUT_DIR = Path(os.environ.get("ECHO_OUTPUT_DIR", str(_ECHO_DIR / "output")))
CACHE_DIR = Path(os.environ.get("ECHO_CACHE_DIR", str(_ECHO_DIR / "cache")))
ECHOMIMIC_DIR = Path(os.environ.get("ECHOMIMIC_REPO", str(_ECHO_DIR / "echomimic_repo")))
PORT = int(os.environ.get("ECHO_PORT", "8081"))

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

logger.info("Config: device=%s half_body=%s ref=%s port=%d", DEVICE, HALF_BODY, REF_IMAGE, PORT)


# ── Models ─────────────────────────────────────────────────────────────────────


class GenerateRequest(BaseModel):
    audio_b64: str = Field(..., description="音频 base64 (mp3/wav)")
    duration_s: Optional[float] = None
    hand_pose: Optional[dict] = None
    ref_image_b64: Optional[str] = None
    cache_key: Optional[str] = None
    emotion: str = "neutral"


class GenerateResponse(BaseModel):
    ok: bool = True
    video_url: Optional[str] = None
    video_b64: Optional[str] = None
    duration_ms: int = 0
    backend: str = "echomimic_v2"
    cached: bool = False
    note: str = ""


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="EchoMimic V2 Sidecar (Native)", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 延迟加载模型
_pipeline: Any = None


def _load_pipeline():
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    logger.info("Loading EchoMimic V2 pipeline...")
    try:
        if ECHOMIMIC_DIR.exists() and (ECHOMIMIC_DIR / "inference.py").exists():
            sys.path.insert(0, str(ECHOMIMIC_DIR))
            # 实际加载 EchoMimic V2 推理管线
            # 此处根据 EchoMimic V2 的实际 API 调整
            _pipeline = {"loaded": True, "device": DEVICE, "model": "EchoMimicV2"}
            logger.info("Pipeline loaded from %s", ECHOMIMIC_DIR)
        else:
            # 无 EchoMimic repo 时进入 stub 模式（开发/测试用）
            logger.warning("EchoMimic repo not found at %s — stub mode", ECHOMIMIC_DIR)
            _pipeline = {"loaded": True, "device": DEVICE, "model": "stub"}
    except Exception as e:
        logger.error("Pipeline load failed: %s", e)
        _pipeline = {"loaded": False, "error": str(e)}
    return _pipeline


def _cache_path(audio_hash: str) -> Path:
    return CACHE_DIR / f"{audio_hash}.mp4"


def _generate_stub_video(audio_path: str, ref_path: str, output_path: str) -> bool:
    """Stub 模式：用 ffmpeg 生成一个占位视频（开发测试用）。"""
    import subprocess
    try:
        # 生成一个 5 秒的彩色渐变视频作为占位
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "color=c=blue:s=384x512:d=5:r=15",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-t", "5",
                output_path,
            ],
            capture_output=True,
            timeout=30,
        )
        return Path(output_path).exists()
    except Exception as e:
        logger.error("Stub video generation failed: %s", e)
        return False


def _generate_video(
    audio_path: str,
    ref_path: str,
    output_path: str,
    hand_pose: Optional[dict] = None,
) -> bool:
    pipe = _load_pipeline()
    if not pipe or not pipe.get("loaded"):
        return False

    if pipe.get("model") == "stub":
        return _generate_stub_video(audio_path, ref_path, output_path)

    # === EchoMimic V2 实际调用 ===
    try:
        import subprocess
        cmd = [
            sys.executable,
            str(ECHOMIMIC_DIR / "inference.py"),
            "--audio_path", audio_path,
            "--ref_image_path", ref_path,
            "--output_path", output_path,
            "--device", DEVICE,
        ]
        if HALF_BODY:
            cmd.append("--half_body")
        if hand_pose:
            hp_path = output_path + ".handpose.json"
            Path(hp_path).write_text(json.dumps(hand_pose))
            cmd.extend(["--hand_pose", hp_path])

        logger.info("Running: %s", " ".join(cmd))
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            cwd=str(ECHOMIMIC_DIR),
        )
        if result.returncode != 0:
            logger.error("EchoMimic failed: %s", result.stderr[:500])
            return False
        return Path(output_path).exists()
    except subprocess.TimeoutExpired:
        logger.error("EchoMimic timed out (>120s)")
        return False
    except Exception as e:
        logger.error("EchoMimic error: %s", e)
        return False


# ── Endpoints ──────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    pipe = _pipeline or {}
    gpu = torch.cuda.is_available()
    return {
        "status": "ok",
        "device": DEVICE,
        "half_body": HALF_BODY,
        "model_loaded": bool(pipe.get("loaded")),
        "model_type": pipe.get("model", "none"),
        "gpu_available": gpu,
        "gpu_name": torch.cuda.get_device_name(0) if gpu else "N/A",
    }


@app.get("/status")
async def status():
    gpu = torch.cuda.is_available()
    return {
        "device": DEVICE,
        "half_body": HALF_BODY,
        "ref_image": REF_IMAGE,
        "output_dir": str(OUTPUT_DIR),
        "cache_dir": str(CACHE_DIR),
        "echomimic_dir": str(ECHOMIMIC_DIR),
        "model_loaded": bool(_pipeline and _pipeline.get("loaded")),
        "gpu_available": gpu,
        "gpu_memory_gb": round(torch.cuda.get_device_properties(0).total_mem / 1e9, 1) if gpu else 0,
    }


@app.post("/generate")
async def generate(req: GenerateRequest) -> GenerateResponse:
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

    # 清理
    try:
        os.unlink(audio_path)
    except OSError:
        pass

    if not success:
        return GenerateResponse(
            ok=False,
            backend="echomimic_v2_error",
            note="generation failed",
        )

    # 6. 缓存
    try:
        import shutil
        shutil.copy2(output_path, cached_path)
    except Exception as e:
        logger.warning("Cache write failed: %s", e)

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
    logger.info("Starting EchoMimic V2 native sidecar on :%d (device=%s)", PORT, DEVICE)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
