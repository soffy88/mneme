"""最小 OCR 服务：POST /ocr (raw image bytes) -> {text, lines:[{text, score, box}], ms}.

无鉴权（仅 compose 内网可达，不映射宿主端口）。不记录图片或识别文本（儿童数据）。
"""

from __future__ import annotations

import io
import threading
import time

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from PIL import Image, ImageOps
from rapidocr_onnxruntime import RapidOCR

app = FastAPI(title="mneme-ocr")
_engine = RapidOCR()
_lock = threading.Lock()
_MAX_BYTES = 12 * 1024 * 1024
_MAX_SIDE = 2000


def _prepare(data: bytes) -> np.ndarray:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size
    scale = min(1.0, _MAX_SIDE / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)))
    return np.asarray(img)[:, :, ::-1]  # RGB -> BGR


def _group_lines(items: list) -> list[dict]:
    """把检测框按行聚合（同一行 y 中心接近），行内按 x 排序。"""
    boxes = []
    for box, text, score in items:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        boxes.append(
            {
                "text": text,
                "score": float(score),
                "x": min(xs),
                "yc": (min(ys) + max(ys)) / 2,
                "h": max(ys) - min(ys),
            }
        )
    boxes.sort(key=lambda b: (b["yc"], b["x"]))
    lines: list[list[dict]] = []
    for b in boxes:
        if lines and abs(lines[-1][-1]["yc"] - b["yc"]) < max(8.0, 0.5 * b["h"]):
            lines[-1].append(b)
        else:
            lines.append([b])
    out = []
    for ln in lines:
        ln.sort(key=lambda b: b["x"])
        out.append(
            {
                "text": " ".join(b["text"] for b in ln),
                "score": round(sum(b["score"] for b in ln) / len(ln), 4),
            }
        )
    return out


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/ocr")
async def ocr(request: Request) -> dict:
    data = await request.body()
    if not data or len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="image missing or too large")
    t0 = time.monotonic()
    try:
        arr = _prepare(data)
    except Exception as exc:
        raise HTTPException(status_code=415, detail="unreadable image") from exc
    with _lock:
        result, _ = _engine(arr)
    lines = _group_lines(result or [])
    return {
        "text": "\n".join(ln["text"] for ln in lines),
        "lines": lines,
        "score": round(sum(ln["score"] for ln in lines) / len(lines), 4) if lines else 0.0,
        "ms": int((time.monotonic() - t0) * 1000),
    }
