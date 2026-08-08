"""苏格拉底会话路由（自 main 拆出）。"""

from __future__ import annotations

import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from obase.db import get_db
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import (
    _ensure_session_owner,
    _ensure_student_self,
    get_current_user,
)
from services.models import KnowledgeCluster, KnowledgeUnit, User, WrongQuestion
from services.socratic_service import (
    end_session,
    escape_session,
    socratic_message_stream,
    start_session,
)

router = APIRouter(tags=["socratic"])


@router.post("/v1/socratic/start")
async def post_socratic_start(
    question_id: UUID = Query(...),
    student_id: UUID = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """开始苏格拉底会话。仅学生本人。"""
    _ensure_student_self(current_user, student_id)
    result = await start_session(db, question_id, student_id)
    await db.commit()
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/v1/socratic/{session_id}/message")
async def post_socratic_message(
    session_id: UUID,
    student_message: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE 流式苏格拉底回复。仅会话归属学生本人。"""
    await _ensure_session_owner(db, current_user, session_id)

    async def event_stream():
        async for chunk in socratic_message_stream(db, session_id, student_message):
            yield chunk
        await db.commit()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/v1/socratic/{session_id}/escape")
async def post_socratic_escape(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """请求答案大纲（非完整答案）。仅会话归属学生本人。"""
    await _ensure_session_owner(db, current_user, session_id)
    result = await escape_session(db, session_id)
    await db.commit()
    return result


@router.post("/v1/socratic/{session_id}/end")
async def post_socratic_end(
    session_id: UUID,
    outcome: str = Query("partial"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """结束会话，写 outcome。仅会话归属学生本人。"""
    await _ensure_session_owner(db, current_user, session_id)
    result = await end_session(db, session_id, outcome)
    await db.commit()
    return result


class SocraticForKuReq(BaseModel):
    ku_id: str
    student_id: UUID


@router.post("/v1/socratic/start-for-ku")
async def post_socratic_start_for_ku(
    body: SocraticForKuReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """为某 KU 发起苏格拉底引导。仅学生本人。"""
    _ensure_student_self(current_user, body.student_id)
    row = (
        await db.execute(
            select(KnowledgeUnit, KnowledgeCluster)
            .join(KnowledgeCluster, KnowledgeUnit.cluster_id == KnowledgeCluster.id)
            .where(KnowledgeUnit.id == body.ku_id)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="KnowledgeUnit not found")
    ku, _kc = row

    q_text = f"【{ku.name}】\n{ku.description or ''}"
    wq = WrongQuestion(
        id=uuid.uuid4(),
        student_id=body.student_id,
        subject="math",
        question_text=q_text,
        knowledge_points={body.ku_id: ku.name},
        needs_image=False,
    )
    db.add(wq)
    await db.flush()

    result = await start_session(db, wq.id, body.student_id)
    await db.commit()
    return result
