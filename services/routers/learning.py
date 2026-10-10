"""Learning product API (SPEC §69): plan / today / lesson / session /
answer / review / progress / vocabulary detail.

All endpoints are student-self (or bound parent). Learning logic lives in
LearningEngine / ContextEngine / ProgressEngine — never in the router.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from obase.db import get_db
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import _ensure_student_self, get_current_user, require_student_access
from services.context_engine import ContextEngine
from services.learning_engine import LearningEngine
from services.models import LearningPlan, User
from services.progress_engine import ProgressEngine

router = APIRouter(tags=["learning"])


# ---------- plan ----------

@router.get("/v1/learning/plan/{student_id}")
async def get_learning_plan(
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_student_self(current_user, student_id)
    from sqlalchemy import select

    plan = (
        await db.execute(
            select(LearningPlan).where(
                LearningPlan.user_id == student_id,
                LearningPlan.status == "ACTIVE",
            )
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="no active learning plan")
    return {
        "id": str(plan.id),
        "primary_scope": plan.primary_scope,
        "current_book_id": plan.current_book_id,
        "current_lesson_id": plan.current_lesson_id,
        "exam_target": plan.exam_target,
        "nce_support_enabled": plan.nce_support_enabled,
        "daily_new_word_target": plan.daily_new_word_target,
        "daily_review_target": plan.daily_review_target,
    }


class UpdatePlanReq(BaseModel):
    current_lesson_id: str | None = None
    exam_target: str | None = None
    nce_support_enabled: bool | None = None
    daily_new_word_target: int | None = None
    daily_review_target: int | None = None


@router.put("/v1/learning/plan/{student_id}")
async def update_learning_plan(
    student_id: UUID,
    payload: UpdatePlanReq = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_student_self(current_user, student_id)
    from sqlalchemy import select

    plan = (
        await db.execute(
            select(LearningPlan).where(
                LearningPlan.user_id == student_id,
                LearningPlan.status == "ACTIVE",
            )
        )
    ).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=404, detail="no active learning plan")
    if payload.current_lesson_id is not None:
        plan.current_lesson_id = payload.current_lesson_id
    if payload.exam_target is not None:
        plan.exam_target = payload.exam_target
    if payload.nce_support_enabled is not None:
        plan.nce_support_enabled = payload.nce_support_enabled
    if payload.daily_new_word_target is not None:
        plan.daily_new_word_target = payload.daily_new_word_target
    if payload.daily_review_target is not None:
        plan.daily_review_target = payload.daily_review_target
    await db.commit()
    return {"id": str(plan.id), "status": "ok"}


# ---------- today ----------

@router.get("/v1/learning/today/{student_id}")
async def get_today(
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_student_self(current_user, student_id)
    engine = LearningEngine(db)
    due = await engine.get_due_reviews(student_id)
    from sqlalchemy import select

    plan = (
        await db.execute(
            select(LearningPlan).where(
                LearningPlan.user_id == student_id,
                LearningPlan.status == "ACTIVE",
            )
        )
    ).scalar_one_or_none()
    new_target = plan.daily_new_word_target if plan else 10
    return {
        "due_reviews": len(due),
        "due_vocab_ids": due,
        "new_target": new_target,
        "current_lesson_id": plan.current_lesson_id if plan else None,
    }


# ---------- courses / books / lessons ----------

@router.get("/v1/courses")
async def list_courses(
    db: AsyncSession = Depends(get_db),
    _auth: User = Depends(require_student_access),
):
    from sqlalchemy import select

    from services.models import Course

    rows = (await db.execute(select(Course))).scalars().all()
    return [{"id": r.id, "scope": r.scope, "series": r.series, "title": r.title} for r in rows]


@router.get("/v1/books")
async def list_books(
    db: AsyncSession = Depends(get_db),
    _auth: User = Depends(require_student_access),
):
    from sqlalchemy import select

    from services.models import Book

    rows = (await db.execute(select(Book))).scalars().all()
    return [{"id": r.id, "book_key": r.book_key, "title": r.title, "edition": r.edition} for r in rows]


@router.get("/v1/lessons")
async def list_lessons(
    book_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _auth: User = Depends(require_student_access),
):
    from sqlalchemy import select

    from services.models import Lesson

    rows = (
        await db.execute(select(Lesson).where(Lesson.book_id == book_id).order_by(Lesson.source_order))
    ).scalars().all()
    return [{"id": r.id, "title": r.title, "source_order": r.source_order} for r in rows]


@router.get("/v1/lessons/{lesson_id}")
async def get_lesson(
    lesson_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: User = Depends(require_student_access),
):
    from sqlalchemy import select

    from services.models import Lesson

    lesson = (await db.execute(select(Lesson).where(Lesson.id == lesson_id))).scalar_one_or_none()
    if lesson is None:
        raise HTTPException(status_code=404, detail="lesson not found")
    return {
        "id": lesson.id,
        "title": lesson.title,
        "source_order": lesson.source_order,
        "audio_uri": lesson.audio_uri,
    }


@router.get("/v1/lessons/{lesson_id}/vocabulary")
async def get_lesson_vocabulary(
    lesson_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: User = Depends(require_student_access),
):
    engine = LearningEngine(db)
    vocab_ids = await engine.get_lesson_vocab(lesson_id)
    return {"lesson_id": lesson_id, "vocab_ids": vocab_ids, "count": len(vocab_ids)}


# ---------- sessions ----------

class CreateSessionReq(BaseModel):
    lesson_id: str | None = None
    mode: str = "LESSON"
    max_items: int = 25


@router.post("/v1/learning/sessions/{student_id}")
async def create_session(
    student_id: UUID,
    payload: CreateSessionReq = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_student_self(current_user, student_id)
    engine = LearningEngine(db)
    from sqlalchemy import select

    plan_row = (
        await db.execute(
            select(LearningPlan).where(
                LearningPlan.user_id == student_id,
                LearningPlan.status == "ACTIVE",
            )
        )
    ).scalar_one_or_none()
    plan_id = plan_row.id if plan_row else None
    if payload.lesson_id:
        built = await engine.build_lesson_session(
            student_id, payload.lesson_id, learning_plan_id=plan_id, max_items=payload.max_items
        )
    else:
        from datetime import datetime, timezone

        from services.models import LearningSession

        session = LearningSession(
            user_id=student_id,
            learning_plan_id=plan_id,
            mode=payload.mode,
            started_at=datetime.now(timezone.utc),
        )
        db.add(session)
        await db.flush()

        class _Empty:
            def __init__(self, sid, items):
                self.session_id = sid
                self.items = items

        built = _Empty(session.id, [])  # type: ignore[assignment]
    await db.commit()
    return {
        "session_id": str(built.session_id),
        "items": [
            {
                "vocabulary_item_id": i.vocabulary_item_id,
                "task_type": i.task_type.value,
                "context_source": i.context_source,
                "sentence_id": i.sentence_id,
            }
            for i in built.items
        ],
    }


@router.get("/v1/learning/sessions/{session_id}")
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    _auth: User = Depends(require_student_access),
):
    from sqlalchemy import select

    from services.models import LearningSession, LearningSessionItem

    session = (await db.execute(select(LearningSession).where(LearningSession.id == session_id))).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    items = (
        await db.execute(
            select(LearningSessionItem).where(LearningSessionItem.session_id == session_id).order_by(LearningSessionItem.sequence)
        )
    ).scalars().all()
    return {
        "id": str(session.id),
        "mode": session.mode,
        "items_presented": session.items_presented,
        "items_correct": session.items_correct,
        "items": [
            {
                "sequence": i.sequence,
                "vocabulary_item_id": i.vocabulary_item_id,
                "task_type": i.task_type,
                "state": i.state,
            }
            for i in items
        ],
    }


class AnswerReq(BaseModel):
    item_sequence: int
    answer: str
    interaction_id: UUID
    used_hint: bool = False
    latency_ms: int | None = None


@router.post("/v1/learning/sessions/{session_id}/answer")
async def submit_answer(
    session_id: UUID,
    payload: AnswerReq = Body(...),
    db: AsyncSession = Depends(get_db),
    _auth: User = Depends(require_student_access),
):
    engine = LearningEngine(db)
    result = await engine.submit_answer(
        session_id,
        payload.item_sequence,
        answer=payload.answer,
        interaction_id=payload.interaction_id,
        used_hint=payload.used_hint,
        latency_ms=payload.latency_ms,
    )
    await db.commit()
    return {
        "score": result.score.value,
        "fsrs_rating": result.fsrs_rating.value,
        "detail": result.detail,
    }


# ---------- vocabulary detail ----------

@router.get("/v1/vocabulary/{vocab_id}")
async def get_vocabulary(
    vocab_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: User = Depends(require_student_access),
):
    from sqlalchemy import select

    from services.models import VocabularyItem

    vocab = (await db.execute(select(VocabularyItem).where(VocabularyItem.id == vocab_id))).scalar_one_or_none()
    if vocab is None:
        raise HTTPException(status_code=404, detail="vocabulary not found")
    return {
        "id": vocab.id,
        "word": vocab.word,
        "meaning_cn": vocab.meaning_cn,
        "normalized_form": vocab.normalized_form,
        "phonetic_uk": vocab.phonetic_uk,
        "phonetic_us": vocab.phonetic_us,
    }


@router.get("/v1/vocabulary/{vocab_id}/contexts")
async def get_vocabulary_contexts(
    vocab_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: User = Depends(require_student_access),
):
    engine = ContextEngine(db)
    nce = await engine.get_nce_contexts(vocab_id)
    return {
        "vocab_id": vocab_id,
        "contexts": [
            {
                "sentence_id": c.sentence_id,
                "english_text": c.english_text,
                "chinese_text": c.chinese_text,
                "start_ms": c.start_ms,
                "end_ms": c.end_ms,
                "audio_uri": c.audio_uri,
                "source": c.source,
            }
            for c in nce
        ],
    }


# ---------- review ----------

@router.get("/v1/reviews/due/{student_id}")
async def get_due_reviews(
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_student_self(current_user, student_id)
    engine = LearningEngine(db)
    due = await engine.get_due_reviews(student_id)
    return {"due": due, "count": len(due)}


# ---------- progress ----------

@router.get("/v1/progress/{student_id}")
async def get_progress(
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_student_self(current_user, student_id)
    engine = ProgressEngine(db)
    zhongkao = await engine.exam_coverage("ZHONGKAO")
    gaokao = await engine.exam_coverage("GAOKAO")
    return {
        "zhongkao": {
            "total": zhongkao.total,
            "touched": zhongkao.touched,
            "mastered": zhongkao.mastered,
            "touched_pct": zhongkao.touched_pct,
            "mastered_pct": zhongkao.mastered_pct,
        },
        "gaokao": {
            "total": gaokao.total,
            "touched": gaokao.touched,
            "mastered": gaokao.mastered,
            "touched_pct": gaokao.touched_pct,
            "mastered_pct": gaokao.mastered_pct,
        },
    }


@router.get("/v1/progress/book/{book_id}/{student_id}")
async def get_book_progress(
    book_id: str,
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_student_self(current_user, student_id)
    engine = ProgressEngine(db)
    bp = await engine.book_progress(book_id)
    return {
        "book_id": bp.book_id,
        "completed_lessons": bp.completed_lessons,
        "total_lessons": bp.total_lessons,
        "lesson_pct": bp.lesson_pct,
        "vocab_mastered": bp.vocab_mastered,
        "vocab_total": bp.vocab_total,
        "vocab_pct": bp.vocab_pct,
    }


@router.get("/v1/progress/exam/{scope}/{student_id}")
async def get_exam_progress(
    scope: str,
    student_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_student_self(current_user, student_id)
    engine = ProgressEngine(db)
    cov = await engine.exam_coverage(scope)
    return {
        "scope": cov.scope,
        "total": cov.total,
        "touched": cov.touched,
        "mastered": cov.mastered,
        "touched_pct": cov.touched_pct,
        "mastered_pct": cov.mastered_pct,
    }
