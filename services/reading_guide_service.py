"""
reading_guide_service.py — 阅读理解引导服务（英语/语文）

3O 边界：接请求 → 鉴权 → 调 omodul.reading_guide_workflow → SSE 返回。
零业务逻辑（引导逻辑全在 oskill 层）。
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import SocraticMode, SocraticSession
from services.anon import anon_ref


async def start_reading_guide(
    db: AsyncSession,
    article_text: str,
    question: str,
    subject: str,
    student_id: uuid.UUID,
) -> dict:
    """开始阅读理解引导会话，返回开场引导问（不含答案）。"""
    from omodul import reading_guide_workflow, ReadingGuideConfig, ReadingGuideInput

    session_id = uuid.uuid4()
    output_dir = Path(f"/tmp/mneme/reading/{session_id}")

    result = await reading_guide_workflow(
        config=ReadingGuideConfig(),
        input_data=ReadingGuideInput(
            article_text=article_text,
            question=question,
            subject=subject,
            student_messages=[],
            user_id=anon_ref(student_id),
        ),
        output_dir=output_dir,
    )

    first_question = result.get("assistant_text", "请先读一遍文章，说说你的初步理解。")

    session = SocraticSession(
        id=session_id,
        student_id=student_id,
        mode=SocraticMode.reading_guide,
        messages={
            "article_text": article_text,
            "question": question,
            "subject": subject,
            "history": [{"role": "assistant", "content": first_question}],
        },
    )
    db.add(session)
    await db.commit()

    return {
        "session_id": str(session_id),
        "first_question": first_question,
        "subject": subject,
    }


async def reading_guide_message_stream(
    db: AsyncSession,
    session_id: uuid.UUID,
    student_message: str,
) -> AsyncGenerator[str, None]:
    """处理学生回复，SSE 流式返回下一个引导问题。"""
    from omodul import reading_guide_workflow, ReadingGuideConfig, ReadingGuideInput

    row = (await db.execute(
        select(SocraticSession).where(SocraticSession.id == session_id)
    )).scalar_one_or_none()

    if not row:
        yield "data: {'error':'session not found'}\n\n"
        return

    messages_data: dict = row.messages or {"article_text": "", "question": "", "subject": "chinese", "history": []}
    article_text: str = messages_data.get("article_text", "")
    question: str     = messages_data.get("question", "")
    subject: str      = messages_data.get("subject", "chinese")
    history: list[dict] = messages_data.get("history", [])

    student_messages = [m["content"] for m in history if m.get("role") == "user"]
    student_messages.append(student_message)

    output_dir = Path(f"/tmp/mneme/reading/{session_id}")

    result = await reading_guide_workflow(
        config=ReadingGuideConfig(),
        input_data=ReadingGuideInput(
            article_text=article_text,
            question=question,
            subject=subject,
            student_messages=student_messages,
            user_id=anon_ref(row.student_id or ""),
        ),
        output_dir=output_dir,
    )

    reply = result.get("assistant_text", "请继续思考。")
    located_passage: bool = result.get("located_passage", False)

    history.append({"role": "user", "content": student_message})
    history.append({"role": "assistant", "content": reply})
    await db.execute(
        update(SocraticSession).where(SocraticSession.id == session_id).values(
            messages={**messages_data, "history": history}
        )
    )
    await db.commit()

    import json
    payload = json.dumps({"reply": reply, "located_passage": located_passage}, ensure_ascii=False)
    yield f"data: {payload}\n\n"
    yield "data: [DONE]\n\n"
