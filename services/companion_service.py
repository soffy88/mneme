"""语音辅导 + AI 陪学陪练（服务层编排）。

- 家长可配：陪练名字、开关、每日上限（分钟）、单次时长上限（分钟）——表 companion_settings；
- 用量：companion_usage（按学生 + 本地日期累计秒数）；
- 日志：companion_messages（学生/伙伴每句话，已 PII 打码，带安全标记），家长可查；
- 大脑：复用 chat_router.tool_chat_turn → mneme_agent tutor_loop + MCP 工具（判分只经工具，
  掌握度只经 SubmitAnswer），陪练模式额外拼入人格 + 安全提示，KC 池取 BKT 最弱的 KU；
- ``VoiceSession``：与 WebSocket 解耦的会话状态机（VAD→ASR 事件 → 安全过滤 → 大脑 → 输出过滤 →
  分句 TTS 流式下发，speech_start/interrupt 即打断）。设计参考 Open-LLM-VTuber，未复用其代码。

三张表都含 student_id → 已入 purge_service._STUDENT_TABLES。
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services import companion_safety as cs
from services.speech_text import split_sentences

CN_TZ = timezone(timedelta(hours=8))
DEFAULTS = {"name": "小智", "enabled": True, "daily_cap_minutes": 30, "session_limit_minutes": 20}
BREAK_EVERY_SECONDS = 10 * 60
TURNS_PER_MINUTE = 12
VOICE_TOOL = "VoiceTutor"
COMPANION_TOOL = "StudyCompanion"
_NAME_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9]{1,8}$")


def today_cn(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(CN_TZ).date().isoformat()


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name or "")) and cs.check_input(name).allowed and not cs._has(name, cs.ROMANCE)


# ---------------- 持久化 ----------------
async def get_settings(db: AsyncSession, student_id: str) -> dict:
    row = (
        await db.execute(
            text(
                "SELECT name, enabled, daily_cap_minutes, session_limit_minutes FROM companion_settings "
                "WHERE student_id = :s"
            ),
            {"s": str(student_id)},
        )
    ).mappings().first()
    return dict(row) if row else dict(DEFAULTS)


async def put_settings(db: AsyncSession, student_id: str, patch: dict, *, updated_by: str) -> dict:
    cur = await get_settings(db, student_id)
    cur.update({k: v for k, v in patch.items() if v is not None and k in DEFAULTS})
    await db.execute(
        text(
            "INSERT INTO companion_settings (student_id, name, enabled, daily_cap_minutes, session_limit_minutes, "
            "updated_by, updated_at) VALUES (:s, :n, :e, :d, :l, :u, now()) "
            "ON CONFLICT (student_id) DO UPDATE SET name=:n, enabled=:e, daily_cap_minutes=:d, "
            "session_limit_minutes=:l, updated_by=:u, updated_at=now()"
        ),
        {"s": str(student_id), "n": cur["name"], "e": cur["enabled"], "d": cur["daily_cap_minutes"],
         "l": cur["session_limit_minutes"], "u": str(updated_by)},
    )
    await db.commit()
    return cur


async def used_seconds_today(db: AsyncSession, student_id: str) -> int:
    v = (
        await db.execute(
            text("SELECT seconds FROM companion_usage WHERE student_id = :s AND day = :d"),
            {"s": str(student_id), "d": today_cn()},
        )
    ).scalar_one_or_none()
    return int(v or 0)


async def add_usage(db: AsyncSession, student_id: str, seconds: int) -> None:
    if seconds <= 0:
        return
    await db.execute(
        text(
            "INSERT INTO companion_usage (student_id, day, seconds) VALUES (:s, :d, :n) "
            "ON CONFLICT (student_id, day) DO UPDATE SET seconds = companion_usage.seconds + :n"
        ),
        {"s": str(student_id), "d": today_cn(), "n": int(seconds)},
    )
    await db.commit()


async def log_message(
    db: AsyncSession, *, student_id: str, session_id: str, mode: str, role: str, content: str, flags: list[str]
) -> None:
    await db.execute(
        text(
            "INSERT INTO companion_messages (id, student_id, session_id, mode, role, content, flags) "
            "VALUES (:i, :s, :ss, :m, :r, :c, :f)"
        ),
        {"i": str(uuid.uuid4()), "s": str(student_id), "ss": session_id, "m": mode, "r": role,
         "c": content[:2000], "f": ",".join(flags)[:200]},
    )
    await db.commit()


async def list_logs(db: AsyncSession, student_id: str, *, limit: int = 100) -> list[dict]:
    rows = (
        await db.execute(
            text(
                "SELECT session_id, mode, role, content, flags, created_at FROM companion_messages "
                "WHERE student_id = :s ORDER BY created_at DESC LIMIT :n"
            ),
            {"s": str(student_id), "n": int(limit)},
        )
    ).mappings().all()
    return [
        {**dict(r), "flags": [f for f in (r["flags"] or "").split(",") if f],
         "created_at": r["created_at"].isoformat() if r["created_at"] else None}
        for r in rows
    ]


async def weak_kcs(db: AsyncSession, student_id: str, *, n: int = 3) -> list[str]:
    rows = (
        await db.execute(
            text(
                "SELECT knowledge_point FROM kc_mastery WHERE student_id = CAST(:s AS uuid) "
                "AND p_mastery IS NOT NULL AND p_mastery < 0.85 ORDER BY p_mastery ASC LIMIT :n"
            ),
            {"s": str(student_id), "n": n},
        )
    ).scalars().all()
    return [str(r) for r in rows]


# ---------------- 大脑 ----------------
Brain = Callable[[str, list[dict], str], Awaitable[str]]


def make_brain(*, student_id: uuid.UUID, auth_token: str, name: str) -> Brain:
    """生产大脑：tool_chat_turn（tutor_loop + MCP 工具），陪练模式拼人格+安全提示、取弱 KU。"""

    async def _brain(message: str, history: list[dict], mode: str) -> str:
        from obase.db import SessionLocal
        from services.chat_router import _classify_llm, tool_chat_turn
        from services.providers.setup import get_agent_loop_caller

        async def _free_qa(_: str) -> str:  # 语音会话内不跳转页面，始终留在对话里
            return '{"mode": "free_qa"}'

        async with SessionLocal() as db:
            kcs = await weak_kcs(db, str(student_id)) if mode == "companion" else []
            out = await tool_chat_turn(
                db, student_id, message=message, history=history[-8:], kc_ids=kcs or None,
                loop_caller=get_agent_loop_caller(),
                classify_llm=_free_qa if mode == "companion" else _classify_llm,
                auth_token=auth_token, extra_system=cs.safety_prompt(name, mode=mode),
                max_iterations=10,
            )
        return str(out.get("reply") or "")

    return _brain


PRACTICE_KICKOFF = (
    "（系统：学生点了'开始练习'。请从当前知识点里选一个最需要巩固的，用 PoseQuestion 出一道适合口头回答的题，"
    "用一两句话把题目读给学生听。）"
)


# ---------------- 会话 ----------------
@dataclass
class SessionLimits:
    name: str
    session_limit_s: int
    remaining_today_s: int


class VoiceSession:
    """一次 /v1/voice 连接的状态机。send 发 JSON 给前端；brain / speech / persist 均可注入。"""

    def __init__(
        self,
        *,
        send: Callable[[dict], Awaitable[None]],
        brain: Brain,
        speech: Any,
        mode: str,
        limits: SessionLimits,
        persist: Callable[[str, str, list[str]], Awaitable[None]],
        rate_check: Optional[Callable[[], Awaitable[bool]]] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.send = send
        self.brain = brain
        self.speech = speech
        self.mode = mode
        self.limits = limits
        self.persist = persist
        self.rate_check = rate_check
        self.clock = clock
        self.started = clock()
        self.history: list[dict] = []
        self.reply_task: Optional[asyncio.Task] = None
        self.last_break = self.started
        self.closed = False
        self.turn_ms: list[int] = []

    # -- 时长 --
    def elapsed(self) -> int:
        return int(self.clock() - self.started)

    def over_limit(self) -> Optional[str]:
        e = self.elapsed()
        if e >= self.limits.remaining_today_s:
            return "daily_cap"
        if e >= self.limits.session_limit_s:
            return "session_limit"
        return None

    async def _speak_text(self, text: str, *, index_base: int = 0) -> None:
        for i, sent in enumerate(split_sentences(text)):
            await self.send({"type": "reply_text", "index": index_base + i, "text": sent})
            try:
                wav, spoken, _hit = await self.speech.tts(sent)
            except Exception:  # noqa: BLE001 - text still delivered
                await self.send({"type": "tts_error", "index": index_base + i})
                continue
            await self.send({
                "type": "audio", "index": index_base + i, "format": "wav",
                "data": base64.b64encode(wav).decode("ascii"),
            })

    async def barge_in(self) -> None:
        if self.reply_task and not self.reply_task.done():
            self.reply_task.cancel()
            try:
                await self.reply_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            await self.send({"type": "interrupted"})

    async def on_asr_event(self, ev: dict) -> None:
        kind = ev.get("type")
        if kind == "speech_start":
            await self.send({"type": "vad", "state": "speech_start"})
            await self.barge_in()
        elif kind == "final":
            txt = str(ev.get("text") or "").strip()
            if txt:
                await self.send({"type": "transcript", "text": txt, "asr_seconds": ev.get("asr_seconds")})
                await self.start_turn(txt)

    async def start_turn(self, text: str, *, system: bool = False) -> None:
        await self.barge_in()
        self.reply_task = asyncio.create_task(self._turn(text, system=system))

    async def _turn(self, text: str, *, system: bool = False) -> None:
        t0 = self.clock()
        reason = self.over_limit()
        if reason:
            await self.end_for_limit(reason)
            return
        if self.rate_check and not await self.rate_check():
            await self.send({"type": "error", "code": "rate_limited", "message": "说得太快啦，休息几秒再说吧"})
            return
        name = self.limits.name
        if system:
            safe_text, flags, verdict = text, [], None
        else:
            verdict = cs.check_input(text, name=name)
            safe_text, flags = verdict.text, verdict.flags
            await self.persist("student", safe_text, flags)
        if verdict is not None and not verdict.allowed:
            reply, out_flags = verdict.reply, ["canned_" + verdict.category]
        else:
            try:
                raw = await self.brain(safe_text, self.history, self.mode)
            except Exception:  # noqa: BLE001 - degrade gracefully
                raw = "我刚才没想好，我们再试一次好吗？"
            reply, out_flags = cs.filter_output(raw, name=name)
            if not system:
                self.history += [{"role": "user", "content": safe_text}, {"role": "assistant", "content": reply}]
        await self.persist("companion", reply, out_flags)
        await self.send({"type": "reply_start", "category": verdict.category if verdict else "system"})
        await self._speak_text(reply)
        if self.mode == "companion" and self.clock() - self.last_break >= BREAK_EVERY_SECONDS:
            self.last_break = self.clock()
            tip = "我们已经学了一会儿啦，站起来活动一下、喝口水、看看远处，休息一下再继续吧！"
            await self.persist("companion", tip, ["break"])
            await self.send({"type": "break_suggestion", "text": tip})
            await self._speak_text(tip, index_base=100)
        self.turn_ms.append(int((self.clock() - t0) * 1000))
        await self.send({"type": "reply_done"})

    async def end_for_limit(self, reason: str) -> None:
        msg = (
            "今天的陪学时间用完啦，明天见！记得把今天学的讲给家人听哦。"
            if reason == "daily_cap"
            else "这次我们学得很认真！先休息一下，过一会儿再来吧。"
        )
        await self.persist("companion", msg, [reason])
        await self.send({"type": "limit", "reason": reason, "text": msg})
        await self._speak_text(msg)
        self.closed = True


def encode_event(ev: dict) -> str:
    return json.dumps(ev, ensure_ascii=False)
