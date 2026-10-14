"""Mneme OCR 服务：POST /ocr (raw image bytes) -> {text, lines:[{text, score, box}], image_w, image_h, ms}.

无鉴权（仅 compose 内网可达，不映射宿主端口）。不记录图片或识别文本（儿童数据）。

流水线（全部 CPU、确定性）：
1. EXIF 转正 → 长边缩到 MNEME_OCR_MAX_SIDE（默认 1600，客户端一般已经压好）；
2. 作业纸透视矫正（找到占画面 ≥35% 的四边形纸张轮廓才做）；
3. 投影法纠偏（±10°，先粗后细）；
4. 去阴影 + CLAHE 对比度增强（灰度图上做，检测/识别都用它）；
5. RapidOCR（det 限长 MNEME_OCR_DET_SIDE=960、线程数固定，避免 cgroup 内超订）；
6. 版面：按行聚合；横线空格（默写/填空的 ____）补回；竖排分数（上数字/横杠/下数字）合并成 (a)/(b)；
   上标（框明显偏上且更小的 2/3）写成 ²/³。
返回的 box 是 **原图（EXIF 转正后）归一化坐标** [x0,y0,x1,y1]，前端可直接叠加在学生上传的图上。

模型在进程启动时加载，并用一张合成图预热一次（首请求不冷启动）。
"""

from __future__ import annotations

import io
import os
import re
import threading
import time
from typing import Any, Optional

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from PIL import Image, ImageOps
from rapidocr_onnxruntime import RapidOCR


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


_THREADS = _env_int("MNEME_OCR_THREADS", _env_int("OMP_NUM_THREADS", 4))
_MAX_SIDE = _env_int("MNEME_OCR_MAX_SIDE", 1600)
_DET_SIDE = _env_int("MNEME_OCR_DET_SIDE", 960)
_PREPROCESS = os.environ.get("MNEME_OCR_PREPROCESS", "1").strip().lower() not in {"0", "false", "off"}
_MAX_BYTES = 12 * 1024 * 1024

app = FastAPI(title="mneme-ocr")
_engine = RapidOCR(
    det_limit_side_len=_DET_SIDE,
    det_limit_type="max",
    intra_op_num_threads=_THREADS,
    inter_op_num_threads=1,
)
_lock = threading.Lock()
_ready = {"ok": False, "warm_ms": None}


# ── 预处理 ────────────────────────────────────────────────────────────────────


def _load(data: bytes) -> np.ndarray:
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGB")
    return np.asarray(img)[:, :, ::-1].copy()  # RGB -> BGR


def _order_quad(pts: np.ndarray) -> np.ndarray:
    """按绕质心的角度排成 左上→右上→右下→左下（图像坐标 y 向下）。
    旧的 sum/diff 取法在页面旋转时会让两个角取到同一个点，透视矫正后整张图被拉坏。"""
    pts = pts.reshape(4, 2).astype(np.float32)
    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    return pts[np.argsort(ang)]


def _quad_ok(q: np.ndarray, shape: tuple[int, int]) -> bool:
    """只接受“像一张纸”的四边形：四个角都在 55°–125°、对边长度比 ≤1.35、四点互不重合。"""
    if len({(round(float(x)), round(float(y))) for x, y in q}) != 4:
        return False
    sides = [float(np.linalg.norm(q[(i + 1) % 4] - q[i])) for i in range(4)]
    if min(sides) < 0.2 * max(shape):
        return False
    if max(sides[0], sides[2]) / max(1e-6, min(sides[0], sides[2])) > 1.35:
        return False
    if max(sides[1], sides[3]) / max(1e-6, min(sides[1], sides[3])) > 1.35:
        return False
    for i in range(4):
        a, b, c = q[i - 1], q[i], q[(i + 1) % 4]
        v1, v2 = a - b, c - b
        cosv = float(np.dot(v1, v2) / max(1e-6, np.linalg.norm(v1) * np.linalg.norm(v2)))
        deg = float(np.degrees(np.arccos(np.clip(cosv, -1.0, 1.0))))
        if not 55.0 <= deg <= 125.0:
            return False
    return True


def _find_page(gray: np.ndarray) -> Optional[np.ndarray]:
    """作业纸四边形（原图坐标）。找不到可信的就返回 None（不矫正比矫错好）。"""
    h, w = gray.shape
    scale = 500.0 / max(h, w)
    small = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    blur = cv2.GaussianBlur(small, (5, 5), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    area = cv2.contourArea(c)
    if area < 0.35 * small.shape[0] * small.shape[1] or area > 0.985 * small.shape[0] * small.shape[1]:
        return None
    approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
    if len(approx) != 4 or not cv2.isContourConvex(approx):
        return None
    q = _order_quad(approx / scale)
    return q if _quad_ok(q, (h, w)) else None


def _skew_angle(gray: np.ndarray) -> float:
    """投影法估计倾斜角（度，逆时针为正）：行投影方差最大的角度。"""
    h, w = gray.shape
    scale = 600.0 / max(h, w)
    small = cv2.resize(gray, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    inv = cv2.adaptiveThreshold(small, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15)
    sh, sw = inv.shape
    center = (sw / 2, sh / 2)

    def score(a: float) -> float:
        m = cv2.getRotationMatrix2D(center, a, 1.0)
        r = cv2.warpAffine(inv, m, (sw, sh), flags=cv2.INTER_NEAREST, borderValue=0)
        prof = r.sum(axis=1, dtype=np.float64)
        return float(np.var(prof))

    best = max(np.arange(-10.0, 10.01, 1.0), key=score)
    best = max(np.arange(best - 1.0, best + 1.01, 0.25), key=score)
    return float(best)


def _enhance(gray: np.ndarray) -> np.ndarray:
    """去阴影（除以大核背景）+ CLAHE。"""
    k = max(15, (min(gray.shape) // 25) | 1)
    bg = cv2.medianBlur(cv2.resize(gray, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA), k // 4 | 1)
    bg = cv2.resize(bg, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_LINEAR)
    norm = cv2.divide(gray, np.maximum(bg, 1), scale=235)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(norm)


def preprocess(bgr: np.ndarray, *, enable: bool = True) -> tuple[np.ndarray, np.ndarray, tuple[int, int]]:
    """返回 (送 OCR 的 BGR 图, 3x3 原图→处理图 变换, 原图(w,h))。"""
    oh, ow = bgr.shape[:2]
    T = np.eye(3, dtype=np.float64)
    s = min(1.0, _MAX_SIDE / max(oh, ow))
    img = bgr
    if s < 1.0:
        img = cv2.resize(bgr, (int(round(ow * s)), int(round(oh * s))), interpolation=cv2.INTER_AREA)
        T = np.diag([s, s, 1.0]) @ T
    if not enable:
        return img, T, (ow, oh)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    quad = _find_page(gray)
    if quad is not None:
        wa = np.linalg.norm(quad[1] - quad[0])
        wb = np.linalg.norm(quad[2] - quad[3])
        ha = np.linalg.norm(quad[3] - quad[0])
        hb = np.linalg.norm(quad[2] - quad[1])
        W, H = int(max(wa, wb)), int(max(ha, hb))
        if W > 200 and H > 200:
            dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], np.float32)
            P = cv2.getPerspectiveTransform(quad, dst)
            gray = cv2.warpPerspective(gray, P, (W, H), flags=cv2.INTER_LINEAR, borderValue=255)
            T = P.astype(np.float64) @ T
    ang = _skew_angle(gray)
    if abs(ang) >= 0.5:
        gh, gw = gray.shape
        R = cv2.getRotationMatrix2D((gw / 2, gh / 2), ang, 1.0)
        gray = cv2.warpAffine(gray, R, (gw, gh), flags=cv2.INTER_LINEAR, borderValue=255)
        T = np.vstack([R, [0, 0, 1]]) @ T
    gray = _enhance(gray)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), T, (ow, oh)


# ── 版面 ──────────────────────────────────────────────────────────────────────


def _blank_segments(gray: np.ndarray, char_h: float) -> list[dict]:
    """横线段（填空 ____ 与分数线）：细、长、孤立；排除整页宽的作业本横格线。"""
    h, w = gray.shape
    # 只看深色墨迹（增强后的灰度 < 120）：作业本淡色格线不进来，压在格线上的填空线也不会和格线连成一条
    inv = ((gray < 120).astype(np.uint8)) * 255
    klen = max(10, int(char_h * 0.55))
    horiz = cv2.morphologyEx(inv, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (klen, 1)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(horiz, 8)
    cand = []
    for i in range(1, n):
        x, y, sw, sh, _area = stats[i]
        if sh > max(4, char_h * 0.25) or sw < char_h * 0.6 or sw > 0.6 * w:
            continue
        # 墨色要够深（打印的填空线/分数线）；作业本淡色横格线在增强后仍明显更浅
        ink = float(np.median(gray[y:y + sh, x:x + sw].min(axis=0)))  # 每列最深处的中位数：整段都得是深色
        if ink > 110:
            continue
        fill = float(_area) / max(1.0, float(sw * sh))
        kind = "eq" if sh >= 6 and fill < 0.75 else "bar"  # 两道横杠中间空心 → 等号
        cand.append({"x0": float(x), "x1": float(x + sw), "y": float(y + sh / 2), "w": float(sw), "kind": kind})
    # 下划线字符 "____" 之间有细缝：同一水平线上间隙很小的碎段先拼起来
    cand.sort(key=lambda o: (round(o["y"] / max(2.0, char_h * 0.15)), o["x0"]))
    merged: list[dict] = []
    for o in cand:
        last = merged[-1] if merged else None
        if (last is not None and o["kind"] == "bar" and last["kind"] == "bar"
                and abs(last["y"] - o["y"]) <= max(3.0, char_h * 0.15)
                and 0 <= o["x0"] - last["x1"] <= max(4.0, char_h * 0.35)):
            last["x1"] = o["x1"]
            last["w"] = last["x1"] - last["x0"]
        else:
            merged.append(dict(o))
    cand = merged
    # 同一水平线上的碎段加起来横贯半页以上 → 是格线被文字打断，整组丢掉
    segs = []
    for sg in cand:
        row = [o for o in cand if abs(o["y"] - sg["y"]) <= max(3.0, char_h * 0.15)]
        if min(o["x0"] for o in row) < 0.1 * w and max(o["x1"] for o in row) > 0.9 * w:
            continue
        if sum(o["w"] for o in row) > 0.5 * w:
            continue
        segs.append(sg)
    return segs


def _box_rect(box: Any) -> tuple[float, float, float, float]:
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return min(xs), min(ys), max(xs), max(ys)


def layout_lines(items: list, gray: Optional[np.ndarray]) -> list[dict]:
    """把检测框按行聚合（同一行 y 中心接近），行内按 x 排序；补填空横线、竖排分数、上标。"""
    boxes: list[dict] = []
    for box, text, score in items:
        x0, y0, x1, y1 = _box_rect(box)
        boxes.append({"text": str(text), "score": float(score), "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                      "x": x0, "yc": (y0 + y1) / 2, "h": max(1.0, y1 - y0)})
    if not boxes:
        return []
    char_h = float(np.median([b["h"] for b in boxes]))
    segs = _blank_segments(gray, char_h) if gray is not None else []

    # 竖排分数：横杠上下各有一个小框且横向重叠
    used: set[int] = set()
    fracs: list[dict] = []
    for sg in segs:
        if sg["w"] > char_h * 6:
            continue
        above = [i for i, b in enumerate(boxes) if i not in used and 0 <= sg["y"] - b["y1"] < char_h * 0.6
                 and b["x0"] < sg["x1"] and b["x1"] > sg["x0"] and (b["x1"] - b["x0"]) <= sg["w"] * 1.6]
        below = [i for i, b in enumerate(boxes) if i not in used and 0 <= b["y0"] - sg["y"] < char_h * 0.6
                 and b["x0"] < sg["x1"] and b["x1"] > sg["x0"] and (b["x1"] - b["x0"]) <= sg["w"] * 1.6]
        if len(above) == 1 and len(below) == 1:
            a, b = boxes[above[0]], boxes[below[0]]
            used.update({above[0], below[0]})
            sg["frac"] = True
            fracs.append({"text": f"({a['text'].strip()})/({b['text'].strip()})",
                          "score": min(a["score"], b["score"]), "x0": min(a["x0"], b["x0"], sg["x0"]),
                          "y0": a["y0"], "x1": max(a["x1"], b["x1"], sg["x1"]), "y1": b["y1"],
                          "x": sg["x0"], "yc": sg["y"], "h": char_h})
    boxes = [b for i, b in enumerate(boxes) if i not in used] + fracs

    boxes.sort(key=lambda b: (b["yc"], b["x"]))
    lines: list[list[dict]] = []
    for b in boxes:
        if lines and abs(np.mean([x["yc"] for x in lines[-1]]) - b["yc"]) < max(8.0, 0.55 * max(b["h"], char_h)):
            lines[-1].append(b)
        else:
            lines.append([b])

    out: list[dict] = []
    for ln in lines:
        ln.sort(key=lambda b: b["x"])
        y0 = min(b["y0"] for b in ln)
        y1 = max(b["y1"] for b in ln)
        lh = y1 - y0
        # 填空横线：落在本行基线附近、与文字框不重叠的线段
        for sg in segs:
            if sg.get("frac") or sg.get("taken"):
                continue
            if sg["kind"] == "eq":
                # 检测器常漏掉孤立的等号：落在本行中线附近、不在文字框里 → 补一个 "="
                if (y0 + 0.2 * lh <= sg["y"] <= y1 - 0.1 * lh and sg["w"] < 2.5 * char_h
                        and not any(b["x0"] - 2 < (sg["x0"] + sg["x1"]) / 2 < b["x1"] + 2 for b in ln)):
                    sg["taken"] = True
                    ln.append({"text": "=", "score": 0.9, "x0": sg["x0"], "y0": y0, "x1": sg["x1"], "y1": y1,
                               "x": sg["x0"], "yc": sg["y"], "h": lh})
                continue
            if sg["w"] < 1.5 * char_h:
                continue  # 太短的横杠是减号/破折号，不是填空线
            if not (y0 + 0.35 * lh <= sg["y"] <= y1 + 0.45 * lh):
                continue
            if any(b["x0"] - 2 < (sg["x0"] + sg["x1"]) / 2 < b["x1"] + 2 and "_" not in b["text"] for b in ln):
                continue
            sg["taken"] = True
            ln.append({"text": "____", "score": 1.0, "x0": sg["x0"], "y0": y0, "x1": sg["x1"], "y1": y1,
                       "x": sg["x0"], "yc": sg["y"], "h": lh, "blank": True})
        ln.sort(key=lambda b: b["x"])
        parts: list[str] = []
        prev: Optional[dict] = None
        for b in ln:
            t = b["text"]
            # 上标：独立小框、明显偏上、内容是 2/3
            if prev is not None and t.strip() in {"2", "3"} and b["h"] < 0.75 * prev["h"] and b["yc"] < prev["yc"] - 0.15 * prev["h"]:
                parts[-1] = parts[-1].rstrip() + ("²" if t.strip() == "2" else "³")
                prev = b
                continue
            if parts and not b.get("blank") and not (prev or {}).get("blank"):
                parts.append(" ")
            parts.append(t)
            prev = b
        text = re.sub(r"(?:_{4})+", "____", "".join(parts).replace("____ ", "____")).strip()
        real = [b for b in ln if not b.get("blank")]
        out.append({
            "text": text,
            "score": round(sum(b["score"] for b in real) / max(1, len(real)), 4),
            "_rect": (min(b["x0"] for b in ln), y0, max(b["x1"] for b in ln), y1),
        })
    return out


def _map_back(rect: tuple[float, float, float, float], T: np.ndarray, size: tuple[int, int]) -> list[float]:
    x0, y0, x1, y1 = rect
    pts = np.array([[x0, y0, 1], [x1, y0, 1], [x1, y1, 1], [x0, y1, 1]], np.float64).T
    inv = np.linalg.inv(T) @ pts
    inv = inv[:2] / inv[2]
    w, h = size
    return [
        round(float(np.clip(inv[0].min() / w, 0, 1)), 4),
        round(float(np.clip(inv[1].min() / h, 0, 1)), 4),
        round(float(np.clip(inv[0].max() / w, 0, 1)), 4),
        round(float(np.clip(inv[1].max() / h, 0, 1)), 4),
    ]


def run_ocr(data: bytes, *, preprocess_on: Optional[bool] = None) -> dict:
    t0 = time.monotonic()
    bgr = _load(data)
    img, T, size = preprocess(bgr, enable=_PREPROCESS if preprocess_on is None else preprocess_on)
    t_pre = time.monotonic()
    with _lock:
        result, _ = _engine(img)
    t_ocr = time.monotonic()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    lines = layout_lines(result or [], gray)
    for ln in lines:
        ln["box"] = _map_back(ln.pop("_rect"), T, size)
    return {
        "text": "\n".join(ln["text"] for ln in lines),
        "lines": lines,
        "score": round(sum(ln["score"] for ln in lines) / len(lines), 4) if lines else 0.0,
        "image_w": size[0],
        "image_h": size[1],
        "ms": int((time.monotonic() - t0) * 1000),
        "timing": {"pre_ms": int((t_pre - t0) * 1000), "ocr_ms": int((t_ocr - t_pre) * 1000)},
    }


def _warmup() -> None:
    from PIL import ImageDraw

    t0 = time.monotonic()
    img = Image.new("RGB", (640, 200), "white")
    ImageDraw.Draw(img).text((20, 80), "warm up 3x + 5 = 20", fill="black")
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    try:
        run_ocr(buf.getvalue())
    finally:
        _ready["ok"] = True
        _ready["warm_ms"] = int((time.monotonic() - t0) * 1000)


@app.on_event("startup")
def _startup() -> None:
    _warmup()


@app.get("/health")
def health() -> dict:
    return {"ok": _ready["ok"], "warm_ms": _ready["warm_ms"], "threads": _THREADS, "det_side": _DET_SIDE}


@app.post("/ocr")
async def ocr(request: Request) -> dict:
    data = await request.body()
    if not data or len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="image missing or too large")
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception as exc:
        raise HTTPException(status_code=415, detail="unreadable image") from exc
    raw = request.query_params.get("pre")
    pre = None if raw is None else raw not in {"0", "false", "off"}
    import anyio

    return await anyio.to_thread.run_sync(lambda: run_ocr(data, preprocess_on=pre))
