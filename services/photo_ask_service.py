"""拍照问题目（/v1/questions/ask）：识别 → 学生确认 → 求解（精确内核优先，LLM 兜底）→ 追问。

识别（全部免费）：
- 本机 CPU OCR sidecar（RapidOCR，compose 服务 ``ocr``，MNEME_OCR_URL，默认 http://ocr:8100）；
- 同时（可选）问已配置的视觉模型（get_vision_caller，Veya VL）。OCR 先回来就先等视觉一小段宽限，
  视觉超时/失败就用 OCR 结果。MNEME_ASK_VISION=0 可关掉视觉。

求解：
- 精确内核（services.ask_kernels：一元一次/二次方程、算术、化学配平）命中 → 毫秒级返回，不调 LLM；
- 否则问文本 LLM（get_optional_text_caller），带超时（MNEME_ASK_LLM_TIMEOUT，默认 35s）；
  失败返回 status=llm_unavailable，前端提示稍后重试——绝不 500。

隐私：图片只进私有桶 question-images（对象键按学生 id 分目录），日志不记题面/图片。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from typing import Any, Optional

from services.ask_kernels import normalize_math_text, solve_exact
from services.logging_config import logger

SUBJECTS = {
    "math": "数学",
    "physics": "物理",
    "chemistry": "化学",
    "english": "英语",
    "chinese": "语文",
    "biology": "生物",
    "other": "其他",
}
_ZH2SUBJECT = {v: k for k, v in SUBJECTS.items()}

_IMAGE_MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"RIFF", "image/webp"),
]
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def sniff_image(data: bytes) -> Optional[str]:
    for magic, ctype in _IMAGE_MAGIC:
        if data.startswith(magic):
            if ctype == "image/webp" and data[8:12] != b"WEBP":
                continue
            return ctype
    return None


def normalize_subject(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip().lower()
    if v in SUBJECTS:
        return v
    return _ZH2SUBJECT.get(value.strip())


def guess_subject(text: str) -> Optional[str]:
    """OCR 路径没有模型给学科时的轻量猜测（只用于默认值，学生可改）。"""
    t = text or ""
    if not t.strip():
        return None
    if re.search(r"化学|配平|方程式|摩尔|溶液|[A-Z][a-z]?\d*\s*\+\s*[A-Z][a-z]?\d*\s*(=|→)", t):
        return "chemistry"
    if re.search(r"速度|加速度|电压|电流|电阻|牛顿|压强|浮力|功率|焦耳|质量为|重力", t):
        return "physics"
    latin = len(re.findall(r"[A-Za-z]", t))
    han = len(re.findall(r"[\u4e00-\u9fff]", t))
    if latin > 20 and latin > 3 * han:
        return "english"
    if re.search(r"\d", t) and re.search(r"[=+\-×÷*/^²]|方程|计算|求|函数|三角形|角|面积|周长", t):
        return "math"
    if han > 30 and not re.search(r"\d", t):
        return "chinese"
    return None


def clean_ocr_text(text: str, subject: Optional[str]) -> str:
    t = (text or "").strip()
    if subject in (None, "math"):
        # 只修 OCR 把变量 x 认成乘号的典型错误；其余保持原样（学生可再改）
        t = re.sub(r"求\s*[×X]\s*的", "求 x 的", t)
        t = re.sub(r"(?<=[0-9])\s*[×X]\s*(?=[+\-=])", "x", t)
    return t


async def _ocr_sidecar(image: bytes) -> dict[str, Any]:
    import httpx

    url = os.environ.get("MNEME_OCR_URL", "http://ocr:8100").rstrip("/") + "/ocr"
    timeout = _env_float("MNEME_ASK_OCR_TIMEOUT", 25.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, content=image, headers={"Content-Type": "application/octet-stream"})
        resp.raise_for_status()
        data = resp.json()
    return {
        "text": str(data.get("text") or ""),
        "confidence": float(data.get("score") or 0.0) or None,
    }


_VISION_PROMPT = (
    "你是中学题目识别助手。请把图片中的题目完整、准确地识别出来（保留题号、选项、数学式子，"
    "数学式子用普通文本或 LaTeX 写），不要解答。只输出 JSON："
    '{"text": "题目原文", "subject": "math|physics|chemistry|english|chinese|biology|other", '
    '"grade": "如 初一/初二/初三/高一，不确定就留空"}'
)


async def _vision(image_b64: str) -> dict[str, Any]:
    from services.providers.setup import get_vision_caller

    caller = get_vision_caller()
    if type(getattr(caller, "caller", caller)).__name__ in {"_MockVLM"}:
        raise RuntimeError("vision provider is mock")
    out = await caller(prompt=_VISION_PROMPT, image_b64=image_b64, response_format="json")
    content = out.get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError:
            content = {"text": content}
    if not isinstance(content, dict):
        raise RuntimeError("vision returned non-object")
    text = str(content.get("text") or "").strip()
    if not text or len(text) < 2:
        raise RuntimeError("vision returned empty text")
    return {
        "text": text,
        "subject": normalize_subject(str(content.get("subject") or "")),
        "grade": (str(content.get("grade") or "").strip() or None),
    }


_vision_cooldown_until = 0.0
_vision_slow = {"n": 0}


def _vision_slow_count_bump() -> None:
    """视觉连续 2 次没赶上宽限期 → 同样冷却（慢到没用也算不可用）。"""
    global _vision_cooldown_until
    _vision_slow["n"] += 1
    if _vision_slow["n"] >= 2:
        _vision_slow["n"] = 0
        _vision_cooldown_until = time.monotonic() + _env_float("MNEME_ASK_VISION_COOLDOWN", 300.0)


async def recognize_image(image: bytes) -> dict[str, Any]:
    """识别题目文字：OCR sidecar 与视觉模型并发，视觉优先、OCR 兜底。永不抛。"""
    import base64

    global _vision_cooldown_until
    t0 = time.monotonic()
    vision_on = os.environ.get("MNEME_ASK_VISION", "1").strip().lower() not in {"0", "false", "off"}
    # 熔断：视觉模型最近失败过就冷却一段时间直接走 OCR，不让每个学生都多等宽限期
    if vision_on and t0 < _vision_cooldown_until:
        vision_on = False
    vision_timeout = _env_float("MNEME_ASK_VISION_TIMEOUT", 20.0)
    vision_grace = _env_float("MNEME_ASK_VISION_GRACE", 4.0)
    ocr_task = asyncio.create_task(_ocr_sidecar(image))
    vis_task: Optional[asyncio.Task] = None
    if vision_on:
        vis_task = asyncio.create_task(
            asyncio.wait_for(_vision(base64.b64encode(image).decode()), timeout=vision_timeout)
        )

    ocr_res: Optional[dict] = None
    try:
        ocr_res = await ocr_task
    except Exception as exc:  # noqa: BLE001
        logger.warning("ask OCR sidecar failed: %s", type(exc).__name__)

    vis_res: Optional[dict] = None
    if vis_task is not None:
        try:
            if ocr_res and ocr_res.get("text"):
                elapsed = time.monotonic() - t0
                remaining = max(0.5, min(vision_grace, vision_timeout - elapsed))
                vis_res = await asyncio.wait_for(asyncio.shield(vis_task), timeout=remaining)
            else:
                vis_res = await vis_task
        except Exception as exc:  # noqa: BLE001
            logger.info("ask vision unavailable: %s", type(exc).__name__)
            if vis_task.done():  # 真失败（非仅宽限期内没回来）→ 熔断冷却
                _vision_cooldown_until = time.monotonic() + _env_float("MNEME_ASK_VISION_COOLDOWN", 300.0)
            else:
                _vision_slow_count_bump()
        finally:
            if not vis_task.done():
                vis_task.cancel()

    ms = int((time.monotonic() - t0) * 1000)
    if vis_res:
        _vision_slow["n"] = 0
        return {
            "text": vis_res["text"],
            "subject": vis_res.get("subject") or guess_subject(vis_res["text"]),
            "grade": vis_res.get("grade"),
            "engine": "vision",
            "ms": ms,
            "confidence": None,
            "ocr_text": (ocr_res or {}).get("text"),
        }
    if ocr_res and ocr_res.get("text"):
        subject = guess_subject(ocr_res["text"])
        return {
            "text": clean_ocr_text(ocr_res["text"], subject),
            "subject": subject,
            "grade": None,
            "engine": "ocr",
            "ms": ms,
            "confidence": ocr_res.get("confidence"),
            "ocr_text": ocr_res["text"],
        }
    return {"text": "", "subject": None, "grade": None, "engine": "none", "ms": ms, "confidence": None}


# ── 求解 ────────────────────────────────────────────────────────────────────

_SOLVE_SYSTEM = (
    "你是耐心的中学老师，面向{grade}学生讲题。用简体中文，语言简单、鼓励式。"
    "先给一句「提示」引导学生自己想（不要直接给答案），再给完整分步解答（每步一句话，最多 8 步），"
    "最后给最终答案和一句考点总结。数学式子用普通文本（如 x^2、√2、1/2）。"
    "只输出 JSON："
    '{{"hint": "一句提示", "steps": ["第1步…", "第2步…"], "answer": "最终答案", "explanation": "一句考点总结"}}'
)


def _grade_label(grade: Optional[str]) -> str:
    return grade.strip() if grade and grade.strip() else "初中"


def _parse_llm_json(content: Any) -> Optional[dict]:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None
    t = content.strip()
    if "```" in t:
        m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
        if m:
            t = m.group(1).strip()
    try:
        data = json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return None
    return data if isinstance(data, dict) else None


async def _llm_call(*, system: str, user: str, max_tokens: int, timeout: float, json_mode: bool) -> Optional[str]:
    from services.providers.setup import get_optional_text_caller

    caller = get_optional_text_caller()
    if caller is None:
        return None
    kwargs: dict[str, Any] = {
        "messages": [{"role": "user", "content": user}],
        "system": system,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = "json"
    try:
        out = await asyncio.wait_for(caller(**kwargs), timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — 超时/网关故障 → 交给调用方降级
        logger.warning("ask LLM call failed: %s", type(exc).__name__)
        return None
    content = out.get("content") if isinstance(out, dict) else None
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content or "") or None


async def solve_question(text: str, subject: Optional[str], grade: Optional[str]) -> dict[str, Any]:
    """返回 {status, solver, kernel, hint, steps, answer, explanation, latency_ms}。永不抛。"""
    t0 = time.monotonic()
    subject = normalize_subject(subject) or guess_subject(text)
    exact = None
    try:
        exact = await solve_exact(text, subject)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ask exact kernel failed: %s", type(exc).__name__)
    if exact is not None:
        return {
            "status": "ok",
            "solver": "kernel",
            **exact.to_dict(),
            "subject": subject,
            "latency_ms": int((time.monotonic() - t0) * 1000),
        }

    timeout = _env_float("MNEME_ASK_LLM_TIMEOUT", 35.0)
    raw = await _llm_call(
        system=_SOLVE_SYSTEM.format(grade=_grade_label(grade)),
        user=f"学科：{SUBJECTS.get(subject or 'other', '其他')}\n题目：\n{text.strip()[:3000]}",
        max_tokens=1200,
        timeout=timeout,
        json_mode=True,
    )
    data = _parse_llm_json(raw) if raw else None
    latency = int((time.monotonic() - t0) * 1000)
    if not data:
        return {
            "status": "llm_unavailable",
            "solver": "none",
            "kernel": None,
            "hint": None,
            "steps": [],
            "answer": None,
            "explanation": None,
            "subject": subject,
            "latency_ms": latency,
        }
    steps_raw = data.get("steps") or []
    if isinstance(steps_raw, str):
        steps_raw = [s for s in re.split(r"\n+", steps_raw) if s.strip()]
    steps = [str(s).strip() for s in steps_raw if str(s).strip()][:12]
    return {
        "status": "ok" if steps or data.get("answer") else "partial",
        "solver": "llm",
        "kernel": None,
        "hint": (str(data.get("hint") or "").strip() or None),
        "steps": steps,
        "answer": (str(data.get("answer") or "").strip() or None),
        "explanation": (str(data.get("explanation") or "").strip() or None),
        "subject": subject,
        "latency_ms": latency,
    }


_FOLLOWUP_SYSTEM = (
    "你是耐心的中学老师，学生刚才看了这道题的讲解但没看懂，正在追问。用简体中文、"
    "短句、举具体例子，一次只讲清一个点，最后问一句检查学生是否理解。不超过 200 字。"
)


async def followup_reply(
    *, question_text: str, solution: Optional[dict], history: list[dict], message: str
) -> dict[str, Any]:
    sol = solution or {}
    context = [f"题目：{question_text.strip()[:2000]}"]
    if sol.get("steps"):
        context.append("已给的解答步骤：\n" + "\n".join(str(s) for s in sol["steps"][:12]))
    if sol.get("answer"):
        context.append(f"答案：{sol['answer']}")
    for turn in history[-6:]:
        who = "学生" if turn.get("role") == "student" else "老师"
        context.append(f"{who}：{str(turn.get('text') or '')[:500]}")
    context.append(f"学生：{message.strip()[:500]}")
    raw = await _llm_call(
        system=_FOLLOWUP_SYSTEM,
        user="\n\n".join(context),
        max_tokens=500,
        timeout=_env_float("MNEME_ASK_LLM_TIMEOUT", 35.0),
        json_mode=False,
    )
    if not raw or not raw.strip():
        return {"reply": "AI 老师有点忙，稍后再试一次吧。", "status": "llm_unavailable"}
    return {"reply": raw.strip()[:2000], "status": "ok"}


def new_image_key(student_id: uuid.UUID, content_type: str) -> str:
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(content_type, "bin")
    return f"ask/{student_id}/{uuid.uuid4().hex}.{ext}"


__all__ = [
    "MAX_IMAGE_BYTES",
    "SUBJECTS",
    "clean_ocr_text",
    "followup_reply",
    "guess_subject",
    "new_image_key",
    "normalize_math_text",
    "normalize_subject",
    "recognize_image",
    "sniff_image",
    "solve_question",
]
