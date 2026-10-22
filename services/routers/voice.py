"""朗读 / 语音辅导 / AI 陪学陪练 路由（服务层）。

- ``POST /v1/tts``                       朗读：LaTeX→口语中文→自托管 TTS，MinIO 按文本哈希缓存，返回 audio/wav
- ``WS   /v1/voice``                     语音会话：首帧 {"type":"auth","token","mode":"tutor|companion"}；
                                         之后二进制 PCM16LE 16kHz 单声道帧，或 {"type":"text"|"interrupt"|"audio_end"|"start_practice"}
- ``GET/PUT /v1/companion/{sid}/settings`` 家长配置（名字/开关/每日上限/单次上限），学生只读
- ``GET  /v1/companion/{sid}/logs``      会话日志（学生本人/绑定家长）
授权：语音会话走 services.tool_grants（VoiceTutor / StudyCompanion 学生默认放行，家长需 admin 显式授予）。
不写掌握度：判分与 BKT 只经 tutor_loop 的 MCP 工具 → SubmitAnswer。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from obase.db import get_db
from services import companion_service as svc
from services.auth_deps import _ensure_student_access, get_current_user
from services.models import ParentStudent, User

router = APIRouter(tags=["voice"])

TTS_PER_MINUTE = 60
MAX_PCM_BYTES_PER_SESSION = 16000 * 2 * 60 * 40  # 40 分钟音频上限
_active: set[str] = set()  # 每个学生同时只允许 1 条语音连接（单进程）


class TtsReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=600)
    speed: float = Field(default=1.0, ge=0.6, le=1.6)


def _speech() -> Any:
    from services.speech_client import get_speech_client

    return get_speech_client()


async def _rate_ok(ident: str, scope: str, limit: int, window: int = 60) -> bool:
    from services.ratelimit import check_rate_limit

    try:
        await check_rate_limit(ident, limit=limit, window_seconds=window, scope=scope)
        return True
    except HTTPException:
        return False
    except Exception:  # noqa: BLE001 - redis down → fail-open for reads only
        return True


@router.post("/v1/tts")
async def post_tts(body: TtsReq, current_user: User = Depends(get_current_user)) -> Response:
    if not await _rate_ok(str(current_user.id), "tts", TTS_PER_MINUTE):
        raise HTTPException(429, "朗读太频繁，请稍后再试")
    from services.speech_client import SpeechError

    try:
        wav, spoken, hit = await _speech().tts(body.text, speed=body.speed)
    except SpeechError as e:
        raise HTTPException(503, f"朗读暂不可用（{e}）") from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(503, "朗读暂不可用") from e
    return Response(
        wav, media_type="audio/wav",
        headers={"X-TTS-Cache": "hit" if hit else "miss", "X-Spoken-Text": quote(spoken[:300]),
                 "Cache-Control": "private, max-age=86400"},
    )


# ---------------- 家长配置 / 日志 ----------------
class CompanionSettingsReq(BaseModel):
    name: Optional[str] = Field(default=None, max_length=8)
    enabled: Optional[bool] = None
    daily_cap_minutes: Optional[int] = Field(default=None, ge=0, le=240)
    session_limit_minutes: Optional[int] = Field(default=None, ge=5, le=90)


async def _is_parent_of(db: AsyncSession, parent: User, student_id: uuid.UUID) -> bool:
    from sqlalchemy import select

    row = (
        await db.execute(
            select(ParentStudent).where(
                ParentStudent.parent_id == parent.id, ParentStudent.student_id == student_id
            )
        )
    ).scalar_one_or_none()
    return row is not None


@router.get("/v1/companion/{student_id}/settings")
async def get_companion_settings(
    student_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> dict:
    await _ensure_student_access(db, current_user, student_id)
    s = await svc.get_settings(db, str(student_id))
    s["used_seconds_today"] = await svc.used_seconds_today(db, str(student_id))
    return s


@router.put("/v1/companion/{student_id}/settings")
async def put_companion_settings(
    student_id: uuid.UUID,
    body: CompanionSettingsReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from obase.admin_identity import is_admin

    if not (is_admin(current_user) or await _is_parent_of(db, current_user, student_id)):
        raise HTTPException(403, "仅绑定家长可修改陪学设置")
    if body.name is not None and not svc.valid_name(body.name):
        raise HTTPException(422, "名字需为 1~8 个中英文或数字，且不含不当内容")
    return await svc.put_settings(db, str(student_id), body.model_dump(), updated_by=str(current_user.id))


@router.get("/v1/companion/{student_id}/logs")
async def get_companion_logs(
    student_id: uuid.UUID,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await _ensure_student_access(db, current_user, student_id)
    return {"items": await svc.list_logs(db, str(student_id), limit=max(1, min(limit, 500)))}


# ---------------- WebSocket ----------------
async def authenticate_ws(token: str, mode: str) -> tuple[Optional[User], str]:
    """返回 (user, 错误码)。错误码空串=通过。"""
    from sqlalchemy import select

    from obase.auth import decode_access_token
    from obase.db import SessionLocal
    from services.tool_grants import is_tool_allowed

    payload = decode_access_token(token or "") if token else None
    if not payload or not payload.get("sub"):
        return None, "unauthorized"
    async with SessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.id == uuid.UUID(payload["sub"]), User.deleted_at.is_(None)))
        ).scalar_one_or_none()
        if not user:
            return None, "unauthorized"
        tool = svc.COMPANION_TOOL if mode == "companion" else svc.VOICE_TOOL
        if not await is_tool_allowed(db, user, tool):
            return None, "forbidden"
    return user, ""


@router.websocket("/v1/voice")
async def voice_ws(ws: WebSocket) -> None:  # pragma: no cover - exercised live; core logic unit-tested
    from obase.db import SessionLocal

    await ws.accept()
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=10))
    except Exception:  # noqa: BLE001
        await ws.close(code=4401)
        return
    mode = "companion" if first.get("mode") == "companion" else "tutor"
    token = str(first.get("token") or "")
    user, err = await authenticate_ws(token, mode)
    if err or user is None:
        await ws.send_text(svc.encode_event({"type": "error", "code": err}))
        await ws.close(code=4403 if err == "forbidden" else 4401)
        return
    sid = str(user.id)
    if sid in _active:
        await ws.send_text(svc.encode_event({"type": "error", "code": "already_connected"}))
        await ws.close(code=4409)
        return
    async with SessionLocal() as db:
        st = await svc.get_settings(db, sid)
        used = await svc.used_seconds_today(db, sid)
    remaining = int(st["daily_cap_minutes"]) * 60 - used
    if not st["enabled"] or remaining <= 0:
        await ws.send_text(svc.encode_event({
            "type": "limit", "reason": "disabled" if not st["enabled"] else "daily_cap",
            "text": "今天的陪学时间用完啦，明天见！" if st["enabled"] else "家长暂时关闭了语音陪学。",
        }))
        await ws.close(code=4429)
        return

    _active.add(sid)
    session_id = str(uuid.uuid4())
    speech = _speech()

    async def send(ev: dict) -> None:
        await ws.send_text(svc.encode_event(ev))

    async def persist(role: str, content: str, flags: list[str]) -> None:
        async with SessionLocal() as db:
            await svc.log_message(db, student_id=sid, session_id=session_id, mode=mode, role=role,
                                  content=content, flags=flags)

    async def rate_check() -> bool:
        return await _rate_ok(sid, "voice_turn", svc.TURNS_PER_MINUTE)

    session = svc.VoiceSession(
        send=send, brain=svc.make_brain(student_id=user.id, auth_token=token, name=st["name"]),
        speech=speech, mode=mode, persist=persist, rate_check=rate_check,
        limits=svc.SessionLimits(st["name"], int(st["session_limit_minutes"]) * 60, remaining),
    )
    stream = speech.open_stream()
    reader: Optional[asyncio.Task] = None
    pcm_total = 0
    try:
        await stream.connect()

        async def pump() -> None:
            async for ev in stream.events():
                await session.on_asr_event(ev)

        reader = asyncio.create_task(pump())
        await send({"type": "ready", "session_id": session_id, "mode": mode, "companion_name": st["name"],
                    "session_limit_s": session.limits.session_limit_s, "remaining_today_s": remaining})
        if mode == "companion":
            greet = f"你好呀，我是你的学习伙伴{st['name']}！想直接问我题目，还是点'开始练习'我们一起练一练？"
            await persist("companion", greet, ["greeting"])
            await session._speak_text(greet)
        while not session.closed:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                pcm_total += len(msg["bytes"])
                if pcm_total > MAX_PCM_BYTES_PER_SESSION:
                    break
                await stream.send(msg["bytes"])
            elif msg.get("text"):
                try:
                    cmd = json.loads(msg["text"])
                except ValueError:
                    continue
                t = cmd.get("type")
                if t == "interrupt":
                    await session.barge_in()
                elif t == "audio_end":
                    await stream.flush()
                elif t == "text":
                    await session.start_turn(str(cmd.get("text") or "")[:500])
                elif t == "start_practice" and mode == "companion":
                    await session.start_turn(svc.PRACTICE_KICKOFF, system=True)
                elif t == "ping":
                    await send({"type": "pong"})
            reason = session.over_limit()
            if reason and not (session.reply_task and not session.reply_task.done()):
                await session.end_for_limit(reason)
        if session.reply_task and not session.closed:
            try:
                await asyncio.wait_for(session.reply_task, timeout=60)
            except Exception:  # noqa: BLE001
                pass
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        try:
            await send({"type": "error", "code": "speech_unavailable"})
        except Exception:  # noqa: BLE001
            pass
    finally:
        _active.discard(sid)
        if reader:
            reader.cancel()
        if session.reply_task and not session.reply_task.done():
            session.reply_task.cancel()
        try:
            await stream.close()
        except Exception:  # noqa: BLE001
            pass
        async with SessionLocal() as db:
            await svc.add_usage(db, sid, session.elapsed())
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
