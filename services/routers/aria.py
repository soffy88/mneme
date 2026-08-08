"""Aria 数字人路由（Director / Perception / Lipsync / Brain / Echo）。

自 services.main 拆出；不写掌握度。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path as _Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from fastapi.responses import FileResponse
from obase.db import SessionLocal
from pydantic import BaseModel
from sqlalchemy import select

from services.aria_director import AriaDirectorInput, AriaDirectorState
from services.aria_director import direct as aria_direct
from services.auth_deps import _ensure_student_self, get_current_user
from services.models import User

router = APIRouter(tags=["aria"])


class AriaActReq(BaseModel):
    student_id: UUID
    event: str = "tick"  # tick | wake | user_message
    message: str | None = None
    history: list[dict] = []
    state: dict | None = None


def _inject_perception_into_state(state_dict: dict) -> dict:
    """自动从缓存注入 perception 到 Director state（前端未传时）。"""
    if state_dict.get("perception"):
        return state_dict
    from services.aria_perception import get_perception_manager

    mgr = get_perception_manager()
    room_key = state_dict.get("room_key", "default")
    cached = mgr.get(room_key=room_key)
    if cached:
        state_dict["perception"] = cached
    return state_dict


@router.post("/v1/aria/act")
async def post_aria_act(
    body: AriaActReq,
    current_user: User = Depends(get_current_user),
):
    """Aria 自主行动一步（Director）。不写掌握度。仅学生本人。"""
    _ensure_student_self(current_user, body.student_id)
    raw_state = dict(body.state or {})
    raw_state = _inject_perception_into_state(raw_state)
    st = AriaDirectorState(**raw_state)
    event = body.event if body.event in ("tick", "wake", "user_message") else "tick"
    out = await aria_direct(
        AriaDirectorInput(
            event=event,  # type: ignore[arg-type]
            message=body.message,
            history=body.history or [],
            state=st,
        )
    )
    return out.model_dump()


@router.get("/v1/aria/runtime")
async def get_aria_runtime():
    """数字人运行时配置（影院 / 口型 / NIM）。无密钥泄露。"""
    from services.aria_media import runtime_features

    nim_base = (os.environ.get("ARIA_NIM_BASE_URL") or "").rstrip("/")
    lip_base = (os.environ.get("ARIA_LIPSYNC_BASE_URL") or "").rstrip("/")
    feats = runtime_features()
    feats["perception"] = True
    return {
        "backend": "nim" if nim_base else ("lipsync_gpu" if lip_base else "cinema"),
        "nim_base_url": nim_base or None,
        "lipsync_base_url": lip_base or None,
        "features": feats,
        "note": (
            "cinema = photoreal stills + GSAP keys + CSS viseme; "
            "set ARIA_LIPSYNC_BASE_URL for LivePortrait/EchoMimic video; "
            "ARIA_NIM_BASE_URL for Audio2Face NIM; "
            "P1 perception via POST /v1/aria/perception."
        ),
    }


class AriaPerceptionReq(BaseModel):
    student_id: UUID
    room_key: str = "default"
    text_description: str = ""
    image_b64: str | None = None
    hint: str = ""


@router.post("/v1/aria/perception")
async def post_aria_perception(
    body: AriaPerceptionReq,
    current_user: User = Depends(get_current_user),
):
    """更新 Aria 场景感知（文本或图片）。"""
    _ensure_student_self(current_user, body.student_id)
    from services.aria_perception import get_perception_manager

    mgr = get_perception_manager()
    if body.image_b64:
        result = await mgr.update_from_image(
            room_key=body.room_key,
            image_b64=body.image_b64,
            hint=body.hint,
            fallback_text=body.text_description,
        )
    else:
        result = await mgr.update_from_text(
            room_key=body.room_key,
            text_description=body.text_description,
        )
    return {"status": "ok", "perception": result}


@router.get("/v1/aria/perception")
async def get_aria_perception(
    student_id: UUID,
    room_key: str = "default",
    current_user: User = Depends(get_current_user),
):
    """获取当前缓存的场景感知。"""
    _ensure_student_self(current_user, student_id)
    from services.aria_perception import get_perception_manager

    mgr = get_perception_manager()
    cached = mgr.get(room_key=room_key)
    if cached is None:
        return {"perception": None, "brief": ""}
    from oprim.vlm_scene import AriaScenePerception

    p = AriaScenePerception(**cached)
    return {"perception": cached, "brief": p.to_director_brief()}


class AriaLipsyncReq(BaseModel):
    student_id: UUID
    text: str
    emotion: str = "warm"
    still_hint: str | None = None


@router.post("/v1/aria/lipsync")
async def post_aria_lipsync(
    body: AriaLipsyncReq,
    current_user: User = Depends(get_current_user),
):
    """口型规划。不写掌握度。"""
    from services.aria_media import LipsyncInput
    from services.aria_media import lipsync as aria_lipsync

    _ensure_student_self(current_user, body.student_id)
    if not (body.text or "").strip():
        raise HTTPException(status_code=400, detail="text required")
    out = await aria_lipsync(
        LipsyncInput(
            text=body.text.strip(),
            emotion=body.emotion or "warm",
            still_hint=body.still_hint,
        )
    )
    return out.model_dump()


@router.get("/v1/aria/media-plan")
async def get_aria_media_plan(action: str = "play_piano"):
    """按 action 返回静图池/clip 规划（可匿名探活）。"""
    from services.aria_media import plan_media

    return plan_media(action).model_dump()


class AriaTtsReq(BaseModel):
    student_id: UUID
    text: str
    voice: str | None = None


@router.post("/v1/aria/tts")
async def post_aria_tts(
    body: AriaTtsReq,
    current_user: User = Depends(get_current_user),
):
    """英文 TTS。不写掌握度。"""
    from services.aria_media import TtsInput, synthesize_tts

    _ensure_student_self(current_user, body.student_id)
    if not (body.text or "").strip():
        raise HTTPException(status_code=400, detail="text required")
    out = await synthesize_tts(TtsInput(text=body.text.strip(), voice=body.voice))
    return out.model_dump()


async def _resolve_token(token: str) -> Optional[User]:
    """JWT → User（WebSocket 鉴权）。"""
    from obase.auth import decode_access_token

    try:
        payload = decode_access_token(token)
        if not payload:
            return None
        uid = payload.get("sub")
        if not uid:
            return None
        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.id == UUID(uid)))
            return result.scalar_one_or_none()
    except Exception:
        return None


@router.websocket("/v1/aria/ws")
async def aria_brain_ws(websocket: WebSocket):
    """WebSocket: Aria 自主行为大脑。"""
    from services.aria_brain import AriaBrain

    await websocket.accept()

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        msg = json.loads(raw)
        if msg.get("type") != "auth":
            await websocket.send_json({"error": "auth_required"})
            await websocket.close()
            return
        token = msg.get("token", "")
        user = await _resolve_token(token)
        if not user:
            await websocket.send_json({"error": "invalid_token"})
            await websocket.close()
            return
    except (TimeoutError, json.JSONDecodeError):
        await websocket.close()
        return

    student_id = str(user.id)

    async def send_fn(cmd: dict) -> None:
        try:
            await websocket.send_json(cmd)
        except Exception:
            pass

    brain = AriaBrain(student_id=student_id, send_fn=send_fn)
    await brain.start()
    await websocket.send_json({"type": "connected", "student_id": student_id})

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = msg.get("kind", msg.get("type", ""))
            text = msg.get("text", msg.get("message", ""))
            if kind:
                await brain.push_event(kind, text)
    except Exception:
        pass
    finally:
        await brain.stop()


class AriaEchoDriveReq(BaseModel):
    student_id: UUID
    audio_b64: str
    hand_pose: dict | None = None
    emotion: str = "neutral"
    action: str = "play_piano"


@router.post("/v1/aria/echo-drive")
async def post_aria_echo_drive(
    body: AriaEchoDriveReq,
    current_user: User = Depends(get_current_user),
):
    """EchoMimic V2 半身驱动视频生成。"""
    from services.aria_media import EchoDriveInput, request_echo_drive

    _ensure_student_self(current_user, body.student_id)
    if not body.audio_b64 or len(body.audio_b64) < 100:
        raise HTTPException(status_code=400, detail="audio_b64 required (min 100 chars)")
    out = await request_echo_drive(
        EchoDriveInput(
            audio_b64=body.audio_b64,
            hand_pose=body.hand_pose,
            emotion=body.emotion,
            action=body.action,
        )
    )
    return out.model_dump()


@router.get("/v1/aria/echo-cache/{filename}")
async def get_aria_echo_cache(filename: str):
    """预烘焙 EchoMimic 视频（可匿名）。仅 .mp4。"""
    if not filename.endswith(".mp4"):
        raise HTTPException(status_code=400, detail="only .mp4 files")
    # routers/ 在 services/ 下 → 仓库根是 parents[2]
    cache_dir = _Path(__file__).resolve().parents[2] / ".echo" / "cache"
    fpath = cache_dir / filename
    if not fpath.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        str(fpath),
        media_type="video/mp4",
        headers={"Cache-Control": "public, max-age=3600"},
    )
