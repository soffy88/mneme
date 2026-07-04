"""
physics_service.py — 物理受力分析引导服务

3O 边界：接请求 → 鉴权 → 调 omodul.force_analysis_workflow → SSE 返回。
零业务逻辑（引导逻辑全在 oskill 层）。

T.10 非数学接入认知主线：会话可选带 ku_id，结束时把结果回写 process_interaction
（伪名化红线保持，omodul 层仍只见 anon_ref）。没有 ku_id 的会话（自由输入题目，
未从知识点入口进入）无法归因到具体 KU，跳过认知更新，不强行瞎猜。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import AsyncGenerator, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import SocraticMode, SocraticSession
from services.anon import anon_ref


async def start_force_analysis(
    db: AsyncSession,
    question_text: str,
    student_id: uuid.UUID,
    ku_id: Optional[str] = None,
) -> dict:
    """开始受力分析引导会话，返回开场引导问（不含答案）。"""
    from omodul import force_analysis_workflow, ForceAnalysisConfig, ForceAnalysisInput

    session_id = uuid.uuid4()
    output_dir = Path(f"/tmp/mneme/force/{session_id}")

    result = await force_analysis_workflow(
        config=ForceAnalysisConfig(),
        input_data=ForceAnalysisInput(
            question_text=question_text,
            student_messages=[],
            user_id=anon_ref(student_id),
        ),
        output_dir=output_dir,
    )

    first_question = result.get("assistant_text", "请先描述一下这道题的情景。")

    session = SocraticSession(
        id=session_id,
        student_id=student_id,
        mode=SocraticMode.force_analysis,
        messages={
            "question_text": question_text,
            "ku_id": ku_id,
            "equation_ready_ever": False,
            "history": [{"role": "assistant", "content": first_question}],
        },
    )
    db.add(session)
    await db.commit()

    return {
        "session_id": str(session_id),
        "first_question": first_question,
    }


async def force_analysis_message_stream(
    db: AsyncSession,
    session_id: uuid.UUID,
    student_message: str,
) -> AsyncGenerator[str, None]:
    """处理学生回复，SSE 流式返回下一个引导问题。"""
    from omodul import force_analysis_workflow, ForceAnalysisConfig, ForceAnalysisInput

    row = (
        await db.execute(
            select(SocraticSession).where(SocraticSession.id == session_id)
        )
    ).scalar_one_or_none()

    if not row:
        yield "data: {'error':'session not found'}\n\n"
        return

    messages_data: dict = row.messages or {"question_text": "", "history": []}
    question_text: str = messages_data.get("question_text", "")
    history: list[dict] = messages_data.get("history", [])

    # 只取 student 消息（按发言顺序）
    student_messages = [m["content"] for m in history if m.get("role") == "user"]
    student_messages.append(student_message)

    output_dir = Path(f"/tmp/mneme/force/{session_id}")
    chunks: list[str] = []

    def on_step(name: str, payload: str) -> None:
        if "::" in payload:
            partial = payload.split("::", 1)[1]
            chunks.append(partial)

    result = await force_analysis_workflow(
        config=ForceAnalysisConfig(),
        input_data=ForceAnalysisInput(
            question_text=question_text,
            student_messages=student_messages,
            user_id=anon_ref(row.student_id or ""),
        ),
        output_dir=output_dir,
        on_step=on_step,
    )

    reply = result.get("assistant_text", "请继续思考。")
    equation_ready: bool = result.get("equation_ready", False)

    # 更新会话历史 + equation_ready_ever（一旦本轮为真，会话内永久记为真——
    # 结束时用它核对客户端上报的 outcome，不盲信）
    history.append({"role": "user", "content": student_message})
    history.append({"role": "assistant", "content": reply})
    equation_ready_ever = (
        bool(messages_data.get("equation_ready_ever")) or equation_ready
    )
    await db.execute(
        update(SocraticSession)
        .where(SocraticSession.id == session_id)
        .values(
            messages={
                **messages_data,
                "history": history,
                "equation_ready_ever": equation_ready_ever,
            }
        )
    )
    await db.commit()

    import json

    payload = json.dumps(
        {"reply": reply, "equation_ready": equation_ready}, ensure_ascii=False
    )
    yield f"data: {payload}\n\n"
    yield "data: [DONE]\n\n"


async def end_force_analysis_session(
    db: AsyncSession, session_id: uuid.UUID, outcome: str = "partial"
) -> dict:
    """结束受力分析会话，结果回写 process_interaction（T.10）。

    红线（同 socratic_service.end_session）：客户端上报的 outcome 只是提示，不可信。
    这里没有标准答案可供 judge_answer 核对，退而用会话内是否曾经 equation_ready
    （oskill 自己判定的"分析完整，可以列方程了"）作为核对信号——client 报 success
    但从未 equation_ready 过，一律降级为 partial（不更新掌握度）。
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    session = (
        await db.execute(
            select(SocraticSession).where(SocraticSession.id == session_id)
        )
    ).scalar_one_or_none()
    if not session:
        return {"error": "session not found"}

    messages_data: dict = session.messages or {}
    ku_id: Optional[str] = messages_data.get("ku_id")
    equation_ready_ever = bool(messages_data.get("equation_ready_ever"))

    effective = outcome
    if outcome == "success" and not equation_ready_ever:
        effective = "partial"

    duration = (
        int((now - session.created_at).total_seconds()) if session.created_at else 0
    )
    from services.models import SocraticOutcome

    await db.execute(
        update(SocraticSession)
        .where(SocraticSession.id == session_id)
        .values(duration_seconds=duration, outcome=SocraticOutcome(effective))
    )
    await db.flush()

    kc_updated = False
    if ku_id and effective in ("success", "failed"):
        from services.cognitive_service import process_interaction

        assert session.student_id is not None
        await process_interaction(
            db,
            student_id=session.student_id,
            kc_id=ku_id,
            is_correct=(effective == "success"),
            question_type="force_analysis",
            source="force_analysis",
            struggled=True,  # 引导式会话本身即"吃力"过程，同苏格拉底
        )
        kc_updated = True

    return {
        "session_id": str(session_id),
        "outcome": effective,
        "client_outcome": outcome,
        "duration_seconds": duration,
        "kc_updated": kc_updated,
    }
