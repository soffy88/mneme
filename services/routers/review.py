"""复习 / 限时小测路由（自 main 拆出）。

含 interleaved 复习队列、due 变式、reveal/submit，以及周期 quiz 检查点。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from obase.db import get_db
from pydantic import BaseModel, Field
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


@router.get("/v2/practice/queue/{student_id}")
async def get_practice_queue(
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Studio /practice 只读队列：FSRS 到期 KC + 即将到期 + 本人错题（不含答案）。

    仅学生本人（错题是过程数据）。练习作答走既有 RequestQuestion/SubmitAnswer 守卫路径。
    """
    _ensure_student_self(current_user, student_id)
    from services.practice_queue_service import practice_queue

    return await practice_queue(db, student_id)


# ── 题目收藏（☆）：仅学生本人；不写证据、不改掌握度/FSRS；返回体不含答案 ──────────


class BookmarkCreate(BaseModel):
    student_id: UUID
    source: Literal["posed", "wrong"]
    question_id: str = Field(min_length=1, max_length=64)


@router.post("/v2/practice/bookmarks", status_code=201)
async def create_bookmark(
    body: BookmarkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """收藏一道题（幂等）。题干/KC 由服务端按归属取；题不存在或非本人 → 404。"""
    _ensure_student_self(current_user, body.student_id)
    from services.bookmark_service import add_bookmark

    bm = await add_bookmark(db, body.student_id, body.source, body.question_id)
    if bm is None:
        await db.rollback()
        raise HTTPException(status_code=404, detail="题目不存在或不属于你")
    await db.commit()
    return bm


@router.get("/v2/practice/bookmarks/{student_id}")
async def get_bookmarks(
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """本人收藏列表（新→旧），不含答案。"""
    _ensure_student_self(current_user, student_id)
    from services.bookmark_service import list_bookmarks

    return {"student_id": str(student_id), "bookmarks": await list_bookmarks(db, student_id)}


@router.delete("/v2/practice/bookmarks/{bookmark_id}")
async def delete_bookmark(
    bookmark_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消收藏：只能删本人的（非本人/不存在一律 404，不泄露存在性）。"""
    from services.bookmark_service import remove_bookmark

    ok = await remove_bookmark(db, current_user.id, bookmark_id)
    if not ok:
        await db.rollback()
        raise HTTPException(status_code=404, detail="收藏不存在")
    await db.commit()
    return {"deleted": True, "id": str(bookmark_id)}
