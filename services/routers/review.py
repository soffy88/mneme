"""复习 / 限时小测路由（自 main 拆出）。

含 interleaved 复习队列、due 变式、reveal/submit，以及周期 quiz 检查点。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from obase.db import get_db
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import (
    _ensure_student_access,
    _ensure_student_self,
    get_current_user,
    require_student_access,
)
from services.cognitive_service import review_queue
from services.models import User
from services.quiz_service import get_or_create_due_quiz, submit_quiz
from services.review_service import get_due_variants, reveal_review_answer, submit_review_answer

router = APIRouter(tags=["review"])


@router.get("/v1/review-queue/{student_id}")
async def get_review_queue(
    student_id: UUID,
    now: datetime | None = None,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """今日复习队列（interleaved）。"""
    try:
        return await review_queue(db, student_id, now=now)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/v1/review/due/{student_id}")
async def get_review_due(
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """到期变式复习题。学生本人或绑定家长。"""
    await _ensure_student_access(db, current_user, student_id)
    return await get_due_variants(db, student_id)


@router.post("/v1/review/reveal/{student_id}")
async def post_review_reveal(
    student_id: UUID,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """揭示复习答案 = 放弃检索 → FSRS Again。"""
    if student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")
    ku_id = payload.get("ku_id")
    if not ku_id:
        raise HTTPException(status_code=422, detail="ku_id required")
    result = await reveal_review_answer(db, student_id, ku_id)
    await db.commit()
    return result


@router.post("/v1/review/submit/{student_id}")
async def post_review_submit(
    student_id: UUID,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交复习作答：判分入 BKT/FSRS，返回参考答案。"""
    if student_id != current_user.id:
        raise HTTPException(status_code=403, detail="Permission denied")
    ku_id = payload.get("ku_id")
    if not ku_id:
        raise HTTPException(status_code=422, detail="ku_id required")
    result = await submit_review_answer(
        db, student_id, ku_id, str(payload.get("answer", ""))
    )
    await db.commit()
    return result


@router.get("/v1/quiz/due/{student_id}")
async def get_quiz_due(
    student_id: UUID,
    _auth: User = Depends(require_student_access),
    db: AsyncSession = Depends(get_db),
):
    """是否到期限时小测；到期则现场生成一份。"""
    return await get_or_create_due_quiz(db, student_id)


class QuizAnswerItem(BaseModel):
    question_id: str
    student_answer: str = ""


class QuizSubmitReq(BaseModel):
    answers: list[QuizAnswerItem]
    time_spent_seconds: int


@router.post("/v1/quiz/{quiz_id}/submit")
async def post_quiz_submit(
    quiz_id: UUID,
    student_id: UUID = Query(...),
    body: QuizSubmitReq = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """提交限时小测，判分回写 BKT/FSRS。仅学生本人。"""
    _ensure_student_self(current_user, student_id)
    return await submit_quiz(
        db,
        student_id,
        quiz_id,
        [a.model_dump() for a in body.answers],
        body.time_spent_seconds,
    )
