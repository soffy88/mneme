"""F.1 — Socratic session service (assembly only)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import KCMastery, SocraticMode, SocraticOutcome, SocraticSession, WrongQuestion


async def start_session(db: AsyncSession, question_id: uuid.UUID, student_id: uuid.UUID) -> dict:
    """Initialize a Socratic session for a wrong question."""
    wq = (await db.execute(
        select(WrongQuestion).where(WrongQuestion.id == question_id)
    )).scalar_one_or_none()
    if not wq:
        return {"error": "question not found"}

    mastery_row = None
    if wq.knowledge_points:
        kc_ids = list(wq.knowledge_points.keys()) if isinstance(wq.knowledge_points, dict) else []
        if kc_ids:
            mastery_row = (await db.execute(
                select(KCMastery)
                .where(KCMastery.student_id == student_id, KCMastery.knowledge_point == kc_ids[0])
            )).scalar_one_or_none()

    p_mastery = mastery_row.p_mastery if mastery_row else 0.5
    mode = SocraticMode.deep if (p_mastery or 0) < 0.4 else SocraticMode.mixed

    session = SocraticSession(
        id=uuid.uuid4(),
        student_id=student_id,
        question_id=question_id,
        mode=mode,
        messages=[],
    )
    db.add(session)
    await db.flush()
    return {
        "session_id": str(session.id),
        "mode": mode.value,
        "first_question": "请仔细审题，你认为这道题考察的是什么知识点？",
    }


async def socratic_message_stream(
    db: AsyncSession,
    session_id: uuid.UUID,
    student_message: str,
) -> AsyncGenerator[str, None]:
    """Yield SSE events for a Socratic turn (red line: no answer leakage)."""
    session = (await db.execute(
        select(SocraticSession).where(SocraticSession.id == session_id)
    )).scalar_one_or_none()
    if not session:
        yield f"data: {json.dumps({'error': 'session not found'})}\n\n"
        return

    wq = (await db.execute(
        select(WrongQuestion).where(WrongQuestion.id == session.question_id)
    )).scalar_one_or_none()

    messages = list(session.messages or [])
    messages.append({"role": "user", "content": student_message})

    # Socratic reply (no LLM in test-safe mode — forward-compatible hook)
    reply = _socratic_reply(student_message, messages, wq)

    messages.append({"role": "assistant", "content": reply})
    await db.execute(
        update(SocraticSession).where(SocraticSession.id == session_id).values(messages=messages)
    )
    await db.flush()

    # SSE: stream reply in chunks
    for word in reply.split():
        yield f"data: {json.dumps({'delta': word + ' '})}\n\n"
    yield f"data: {json.dumps({'done': True, 'turn': len([m for m in messages if m['role'] == 'assistant'])})}\n\n"


def _socratic_reply(student_message: str, history: list, wq: Optional[WrongQuestion]) -> str:
    """Deterministic Socratic reply — red line enforced: never reveal correct_answer."""
    if not history or len(history) <= 1:
        return "你的思路是什么？先列出已知条件。"
    return "很好，继续往下想，下一步你会怎么做？"


async def escape_session(db: AsyncSession, session_id: uuid.UUID) -> dict:
    """Return answer outline, mark escape hatch used."""
    session = (await db.execute(
        select(SocraticSession).where(SocraticSession.id == session_id)
    )).scalar_one_or_none()
    if not session:
        return {"error": "session not found"}
    await db.execute(
        update(SocraticSession).where(SocraticSession.id == session_id)
        .values(used_escape_hatch=True)
    )
    wq = (await db.execute(
        select(WrongQuestion).where(WrongQuestion.id == session.question_id)
    )).scalar_one_or_none()
    # Return outline, NOT the full answer
    return {"outline": ["分析题意", "列出公式", "代入计算", "验证答案"], "note": "思路提示，非标准答案"}


async def end_session(db: AsyncSession, session_id: uuid.UUID, outcome: str = "partial") -> dict:
    """End session, map outcome to FSRS rating."""
    outcome_map = {"success": SocraticOutcome.success, "partial": SocraticOutcome.partial,
                   "failed": SocraticOutcome.failed, "abandoned": SocraticOutcome.abandoned}
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
    return {"session_id": str(session_id), "outcome": outcome, "duration_seconds": duration}
