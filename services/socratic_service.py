"""F.1 — Socratic session service (assembly only).

Layer-4 rule: assembly + DB only; business logic lives in omodul/oskill.
"""
from __future__ import annotations

import json
import re as _re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from omodul.socratic_session_workflow import (
    SocraticConfig,
    SocraticInput,
    socratic_session_workflow,
)
from services.models import KCMastery, SocraticMode, SocraticOutcome, SocraticSession, WrongQuestion

from oskill.metacog_scaffold import metacog_scaffold, MetacogScaffoldInput
from obase.provider_registry import ProviderRegistry



async def start_session(db: AsyncSession, question_id: uuid.UUID, student_id: uuid.UUID) -> dict:
    """Initialize a Socratic session; call omodul for first_question."""
    wq = (await db.execute(
        select(WrongQuestion).where(WrongQuestion.id == question_id)
    )).scalar_one_or_none()
    if not wq:
        return {"error": "question not found"}

    kc_id = ""
    mastery_row = None
    if wq.knowledge_points:
        kc_ids = list(wq.knowledge_points.keys()) if isinstance(wq.knowledge_points, dict) else []
        if kc_ids:
            kc_id = kc_ids[0]
            mastery_row = (await db.execute(
                select(KCMastery)
                .where(KCMastery.student_id == student_id, KCMastery.knowledge_point == kc_id)
            )).scalar_one_or_none()

    p_mastery = mastery_row.p_mastery if mastery_row else 0.5
    mode = "deep" if (p_mastery or 0) < 0.4 else "mixed"

    session_id = uuid.uuid4()
    session = SocraticSession(
        id=session_id,
        student_id=student_id,
        question_id=question_id,
        mode=SocraticMode.deep if mode == "deep" else SocraticMode.mixed,
        messages=[],
    )
    db.add(session)
    await db.flush()

    # 强制元认知支架 (Metacog Scaffold)
    metacog_options = []
    first_q = "请仔细审题，你认为这道题考察的是什么知识点？"
    if mode != "sprint":
        try:
            caller = ProviderRegistry.get().llm() if ProviderRegistry._instance else None
        except Exception:
            caller = None
        try:
            meta_res = await metacog_scaffold(
                MetacogScaffoldInput(
                    question=wq.question_text or "未知题目",
                    student_id=str(student_id),
                    input_content="刚开始看题"
                ),
                caller=caller
            )
            metacog_data = meta_res.self_eval
            first_q = metacog_data.get("question", first_q)
            metacog_options = metacog_data.get("options", [])
            
            # Record it as the first system/assistant message in SocraticSession
            session.messages = [{"role": "assistant", "content": first_q, "options": metacog_options}]
            await db.flush()
        except Exception:
            pass # fallback to default if metacog fails

    result = await socratic_session_workflow(
        config=SocraticConfig(mode=mode, max_turns=20),
        input_data=SocraticInput(
            question_text=wq.question_text or "",
            correct_answer=wq.correct_answer or "",
            kc_id=kc_id,
            profiler_result={},
            student_messages=[],
            user_id=str(student_id),
        ),
        output_dir=Path(f"/tmp/mneme/socratic/{session_id}"),
        on_step=None,
    )

    if mode == "sprint" or not metacog_options:
        first_q = result.get("first_question", first_q)
        
    return {
        "session_id": str(session_id),
        "mode": mode,
        "first_question": first_q,
        "metacog_options": metacog_options
    }


async def socratic_message_stream(
    db: AsyncSession,
    session_id: uuid.UUID,
    student_message: str,
) -> AsyncGenerator[str, None]:
    """Yield SSE events for a Socratic turn via omodul (red line: no answer leakage)."""
    session = (await db.execute(
        select(SocraticSession).where(SocraticSession.id == session_id)
    )).scalar_one_or_none()
    if not session:
        yield f"data: {json.dumps({'error': 'session not found'})}\n\n"
        return

    wq = (await db.execute(
        select(WrongQuestion).where(WrongQuestion.id == session.question_id)
    )).scalar_one_or_none()
    if not wq:
        yield f"data: {json.dumps({'error': 'question not found'})}\n\n"
        return

    kc_id = ""
    if wq.knowledge_points:
        kcs = list(wq.knowledge_points.keys()) if isinstance(wq.knowledge_points, dict) else []
        if kcs:
            kc_id = kcs[0]

    messages = list(session.messages or [])

    # H.3: verify_step deterministic intercept before Socratic reply
    step_error = _try_verify_step(student_message)

    sse_chunks: list[str] = []

    if step_error:
        reply = "这一步有问题，再想想。" + step_error
        sse_chunks = reply.split()
    else:
        # Extract accumulated student messages (user role only)
        student_msgs = [m["content"] for m in messages if m.get("role") == "user"]
        student_msgs.append(student_message)

        result = await socratic_session_workflow(
            config=SocraticConfig(
                mode=session.mode.value if session.mode else "mixed",
                max_turns=20,
            ),
            input_data=SocraticInput(
                question_text=wq.question_text or "",
                correct_answer=wq.correct_answer or "",
                kc_id=kc_id,
                profiler_result={},
                student_messages=student_msgs,
                user_id=str(session.student_id),
            ),
            output_dir=Path(f"/tmp/mneme/socratic/{session_id}"),
            on_step=None,
        )
        reply = result.get("first_question", "继续思考，下一步怎么做？")
        sse_chunks = reply.split()

    messages.append({"role": "user", "content": student_message})
    messages.append({"role": "assistant", "content": reply})
    await db.execute(
        update(SocraticSession).where(SocraticSession.id == session_id).values(messages=messages)
    )
    await db.flush()

    turn = len([m for m in messages if m.get("role") == "assistant"])
    for chunk in sse_chunks:
        yield f"data: {json.dumps({'delta': chunk + ' '})}\n\n"
    yield f"data: {json.dumps({'done': True, 'turn': turn})}\n\n"

# 纯算术片段：仅数字/运算符/括号/小数/常见 unicode 运算符（无变量/文字）
_ARITH_CHARS = r"\d\s+\-*/^().,×÷·"
_ARITH_LEFT = _re.compile(rf"[{_ARITH_CHARS}]+$")
_ARITH_RIGHT = _re.compile(rf"^[{_ARITH_CHARS}]+")


def _normalize_arith(s: str) -> str:
    """归一为 sympy 可解析：× ÷ · → * /，^ → **，去千分位逗号/空格。"""
    return (s.replace("×", "*").replace("·", "*").replace("÷", "/")
             .replace("^", "**").replace(",", "").replace("，", "").strip())


def _try_verify_step(message: str) -> Optional[str]:
    """确定性步骤拦截（H.3，红线：确定性、不泄露答案）。

    只拦**纯算术等式且不成立**的情形（如 "2+3=6"）——用 sympy(verify_step) 判定。
    含变量的等式（如 "x=2"）无法脱离上下文判真伪，一律**不拦**，避免误伤正确步骤。
    返回错误提示（不含正确数值）或 None。
    """
    if "=" not in message:
        return None
    for m in _re.finditer("=", message):
        i = m.start()
        left = _ARITH_LEFT.search(message[:i])
        right = _ARITH_RIGHT.search(message[i + 1:])
        if not left or not right:
            continue
        a, b = left.group().strip(), right.group().strip()
        # 两侧都必须含数字，且都是纯算术（否则可能含变量/文字 → 跳过）
        if not (_re.search(r"\d", a) and _re.search(r"\d", b)):
            continue
        try:
            from oprim.verify_step import StepVerifyInput, verify_step
            result = verify_step(StepVerifyInput(
                step_number=1,
                before_lhs=_normalize_arith(a), before_rhs=_normalize_arith(b),
                after_lhs="0", after_rhs="0",   # 检验 a == b 是否成立
            ))
            if result.error_type == "parse_error":
                continue
            if not result.is_correct:
                return "（这一步的算式好像对不上，自己再算一遍这步看看。）"
        except Exception:
            continue
    return None


async def escape_session(db: AsyncSession, session_id: uuid.UUID) -> dict:
    """Return answer outline; never reveal full correct_answer (red line)."""
    session = (await db.execute(
        select(SocraticSession).where(SocraticSession.id == session_id)
    )).scalar_one_or_none()
    if not session:
        return {"error": "session not found"}
    await db.execute(
        update(SocraticSession).where(SocraticSession.id == session_id)
        .values(used_escape_hatch=True)
    )
    return {"outline": ["分析题意", "列出公式", "代入计算", "验证答案"], "note": "思路提示，非标准答案"}


async def end_session(db: AsyncSession, session_id: uuid.UUID, outcome: str = "partial") -> dict:
    """End session, map outcome to FSRS rating."""
    outcome_map = {
        "success": SocraticOutcome.success,
        "partial": SocraticOutcome.partial,
        "failed": SocraticOutcome.failed,
        "abandoned": SocraticOutcome.abandoned,
    }
    soc_outcome = outcome_map.get(outcome, SocraticOutcome.partial)
    now = datetime.now(timezone.utc)
    session = (await db.execute(
        select(SocraticSession).where(SocraticSession.id == session_id)
    )).scalar_one_or_none()
    if not session:
        return {"error": "session not found"}
    duration = int((now - session.created_at).total_seconds()) if session.created_at else 0
    await db.execute(
        update(SocraticSession).where(SocraticSession.id == session_id)
        .values(outcome=soc_outcome, duration_seconds=duration)
    )
    await db.flush()

    # 苏格拉底结果驱动认知更新（Master：outcome 映射 FSRS rating）
    #   success → 答对；failed → 答错(struggled)；partial/abandoned → 不更新
    kc_updated = False
    if outcome in ("success", "failed"):
        wq = (await db.execute(
            select(WrongQuestion).where(WrongQuestion.id == session.question_id)
        )).scalar_one_or_none()
        if wq and wq.knowledge_points:
            kc_id = next(iter(wq.knowledge_points.keys()))
            from services.cognitive_service import process_interaction
            await process_interaction(
                db,
                student_id=session.student_id,
                kc_id=kc_id,
                is_correct=(outcome == "success"),
                question_type="solve",
                question_id=session.question_id,
                source="socratic",
                struggled=True,   # 苏格拉底本身即"吃力"过程（努力收益 M-F）
            )
            kc_updated = True

    return {
        "session_id": str(session_id),
        "outcome": outcome,
        "duration_seconds": duration,
        "kc_updated": kc_updated,
    }
