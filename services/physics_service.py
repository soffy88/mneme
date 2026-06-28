"""
physics_service.py — 物理受力分析引导服务

3O 边界：接请求 → 鉴权 → 调 omodul.force_analysis_workflow → SSE 返回。
零业务逻辑（引导逻辑全在 oskill 层）。
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import SocraticMode, SocraticSession


async def start_force_analysis(
    db: AsyncSession,
    question_text: str,
    student_id: uuid.UUID,
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
            user_id=str(student_id),
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

    row = (await db.execute(
        select(SocraticSession).where(SocraticSession.id == session_id)
    )).scalar_one_or_none()

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
            user_id=str(row.student_id or ""),
        ),
        output_dir=output_dir,
        on_step=on_step,
    )

    reply = result.get("assistant_text", "请继续思考。")
    equation_ready: bool = result.get("equation_ready", False)

    # 更新会话历史
    history.append({"role": "user", "content": student_message})
    history.append({"role": "assistant", "content": reply})
    await db.execute(
        update(SocraticSession).where(SocraticSession.id == session_id).values(
            messages={**messages_data, "history": history}
        )
    )
    await db.commit()

    import json
    payload = json.dumps({"reply": reply, "equation_ready": equation_ready}, ensure_ascii=False)
    yield f"data: {payload}\n\n"
    yield "data: [DONE]\n\n"
