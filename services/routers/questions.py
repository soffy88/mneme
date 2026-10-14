"""拍照问题目 / 做题记录 / 错题本 / 10 分钟错题复习 路由（学生本人，需登录）。

- POST /v1/questions/ask                       拍照或输入题目 → 识别文字（学生可改）
- POST /v1/questions/ask/{ask_id}/solve        求解（精确内核优先，LLM 兜底，带超时）
- POST /v1/questions/ask/{ask_id}/feedback     懂了 / 没懂
- POST /v1/questions/ask/{ask_id}/followup     没懂 → 追问
- POST /v1/questions/ask/{ask_id}/report       「这道题算错了？」反馈（识别错/答案错/步骤看不懂/其他）
- GET  /v1/questions/summary?days=7            近 N 天每天 题数/正确率/错得最多的知识点（家长视图预留）
- POST /v1/wrongbook/add                       一键加入错题本（任意记录）
- GET  /v1/questions/history[/{id}]            做题记录（筛选：学科/来源/对错/日期）
- GET  /v1/questions/records/{id}/image        私有图片（鉴权后回字节，不出签名 URL）
- GET  /v1/review/today                        今天 ~10 分钟的错题复习
- POST /v1/review/today/answer                 提交一题（确定性判分优先）
- POST /v1/review/today/finish                 结束 → 连续天数、剩余到期
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from obase.db import get_db
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import get_current_user
from services.logging_config import logger
from services.models import QuestionRecord, User
from services.ratelimit import rate_limit

router = APIRouter(tags=["questions"])

_ask_rate_limit = rate_limit(limit=30, window_seconds=60, scope="ask")


async def _own_record(db: AsyncSession, user: User, record_id: UUID) -> QuestionRecord:
    rec = await db.get(QuestionRecord, record_id)
    if rec is None or rec.student_id != user.id:
        raise HTTPException(status_code=404, detail="题目不存在")
    return rec


# ── 拍照问题目 ──────────────────────────────────────────────────────────────


@router.post("/v1/questions/ask")
async def post_ask(
    image: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    subject: Optional[str] = Form(None),
    grade: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_ask_rate_limit),
):
    from services.photo_ask_service import (
        MAX_IMAGE_BYTES,
        guess_subject,
        new_image_key,
        normalize_subject,
        recognize_image,
        sniff_image,
    )

    typed = (text or "").strip()
    data: bytes = b""
    if image is not None:
        data = await image.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="图片太大了，请换一张小一点的（10MB 以内）")
        if data and sniff_image(data) is None:
            raise HTTPException(status_code=415, detail="只支持 JPG / PNG / WebP 图片")
    if not data and not typed:
        raise HTTPException(status_code=422, detail="请拍一张题目照片，或者直接输入题目")

    subj = normalize_subject(subject)
    image_key: Optional[str] = None
    warning: Optional[str] = None
    ocr = {"engine": "typed", "ms": 0, "confidence": None}
    lines: list = []
    image_w = image_h = None
    out_text = typed
    out_grade = (grade or "").strip() or current_user.grade or None
    if data:
        ctype = sniff_image(data) or "image/jpeg"
        key = new_image_key(current_user.id, ctype)
        try:
            from services.storage import upload_question_image

            await asyncio.to_thread(upload_question_image, key, data, ctype)
            image_key = key
        except Exception as exc:  # noqa: BLE001 — 存图失败不挡识别
            logger.warning("ask image store failed: %s", type(exc).__name__)
            warning = "图片暂时没保存成功，但不影响解题"
        if not typed:
            rec = await recognize_image(data)
            out_text = rec["text"]
            subj = subj or rec.get("subject")
            out_grade = out_grade or rec.get("grade")
            ocr = {"engine": rec["engine"], "ms": rec["ms"], "confidence": rec.get("confidence")}
            lines = list(rec.get("lines") or [])
            image_w, image_h = rec.get("image_w"), rec.get("image_h")
            if not out_text:
                warning = "没看清题目，请手动输入或重新拍一张（光线亮一点、对准题目）"
    subj = subj or guess_subject(out_text)

    rid = uuid.uuid4()
    db.add(
        QuestionRecord(
            id=rid,
            student_id=current_user.id,
            source="photo_ask",
            subject=subj,
            grade=(out_grade or None) and str(out_grade)[:10],
            question_text=out_text or None,
            image_key=image_key,
            meta={"ocr": ocr},
        )
    )
    await db.commit()
    return {
        "ask_id": str(rid),
        "record_id": str(rid),
        "text": out_text,
        "subject": subj,
        "grade": out_grade,
        "has_image": bool(image_key),
        "ocr": ocr,
        "lines": lines,
        "image_w": image_w,
        "image_h": image_h,
        **({"warning": warning} if warning else {}),
    }


class SolveReq(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    subject: Optional[str] = None
    grade: Optional[str] = None
    # 多题图片：上一次 /solve 返回 status="multi" 时，学生选中的那一题的 index
    question_index: Optional[int] = Field(default=None, ge=0, le=50)


@router.post("/v1/questions/ask/{ask_id}/solve")
async def post_ask_solve(
    ask_id: UUID,
    body: SolveReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_ask_rate_limit),
):
    from services.photo_ask_service import normalize_subject, solve_question

    uid = current_user.id  # rollback 后 ORM 对象过期，先取出
    rec = await _own_record(db, current_user, ask_id)
    subject = normalize_subject(body.subject) or rec.subject
    grade = (body.grade or "").strip() or rec.grade
    original_text = rec.question_text
    await db.rollback()  # 释放连接：求解可能要几十秒，不占着事务

    result = await solve_question(body.text, subject, grade, question_index=body.question_index)

    from services.question_record_service import update_record

    if result.get("status") == "multi":
        # 还没选题：只记下题目列表，不改题面/答案
        await update_record(ask_id, uid, meta={"multi": [q.get("label") for q in result.get("questions") or []]})
        return {"ask_id": str(ask_id), **result}

    if result.get("status") == "no_exact_solver":
        result["references"] = await _textbook_refs(db, result.get("question_text") or body.text, result.get("subject"))

    meta: dict = {
        "solution": {
            k: result.get(k)
            for k in (
                "status", "solver", "kernel", "hint", "steps", "answer", "explanation", "card", "latency_ms",
                "answer_value", "answer_kind", "unit", "check",
            )
            if k in result
        }
    }
    if result.get("similar"):
        meta["similar"] = [q.get("text") for q in result["similar"]][:3]
    solved_text = (result.get("question_text") or body.text).strip()
    if original_text and original_text.strip() != body.text.strip():
        meta["ocr_text_edited"] = True
    if body.question_index is not None:
        meta["picked_index"] = body.question_index
    await update_record(
        ask_id,
        uid,
        question_text=solved_text,
        subject=result.get("subject") or subject,
        grade=grade,
        correct_answer=result.get("answer"),
        meta=meta,
    )
    return {"ask_id": str(ask_id), **result}


async def _textbook_refs(db: AsyncSession, text: str, subject: Optional[str]) -> list[dict]:
    """no_exact_solver 时补充 ≤3 段教材原文（词面/向量检索，3 秒超时，失败返回空列表）。"""
    try:
        from services.knowledge_hub_search import search_knowledge_base

        out = await asyncio.wait_for(search_knowledge_base(db, query=text[:300], top_k=6), timeout=3.0)
    except Exception as exc:  # noqa: BLE001
        logger.info("ask textbook refs skipped: %s", type(exc).__name__)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return []
    refs = []
    for r in out.get("results") or []:
        meta = r.get("textbook_meta") or {}
        if subject and meta.get("subject") and meta.get("subject") != subject:
            continue
        refs.append(
            {
                "content": str(r.get("content") or "")[:300],
                "book_name": meta.get("book_name"),
                "grade": meta.get("grade"),
                "page_number": r.get("page_number"),
                "score": r.get("score"),
            }
        )
        if len(refs) >= 3:
            break
    try:
        await db.rollback()
    except Exception:  # noqa: BLE001
        pass
    return refs


class FeedbackReq(BaseModel):
    understood: bool
    hints_used: Optional[int] = Field(default=None, ge=0, le=20)


@router.post("/v1/questions/ask/{ask_id}/feedback")
async def post_ask_feedback(
    ask_id: UUID,
    body: FeedbackReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rec = await _own_record(db, current_user, ask_id)
    rec.understood = body.understood
    if body.hints_used is not None:
        rec.hints_used = body.hints_used
    rec.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


class ReportReq(BaseModel):
    reason: Literal["识别错了", "答案错了", "步骤看不懂", "其他", "ocr", "answer", "steps", "other"] = "其他"
    comment: Optional[str] = Field(default=None, max_length=500)


@router.post("/v1/questions/ask/{ask_id}/report")
async def post_ask_report(
    ask_id: UUID,
    body: ReportReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """「这道题算错了？」：记到该题记录的 meta.reports（只追加，最多 10 条），供内核/OCR 回归用。"""
    rec = await _own_record(db, current_user, ask_id)
    meta = dict(rec.meta or {})
    reports = list(meta.get("reports") or [])
    raw_sol = meta.get("solution")
    sol: dict = raw_sol if isinstance(raw_sol, dict) else {}
    reports.append(
        {
            "reason": body.reason,
            "comment": (body.comment or "").strip()[:500] or None,
            "solver": sol.get("solver"),
            "kernel": sol.get("kernel"),
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    meta["reports"] = reports[-10:]
    rec.meta = meta
    rec.updated_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info("ask report recorded (reason=%s, kernel=%s)", body.reason, sol.get("kernel"))
    return {"ok": True}


@router.get("/v1/questions/summary")
async def get_questions_summary(
    days: int = Query(7, ge=1, le=90),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """近 N 天（北京时间自然日）每天：题数、已判分数、对/错、正确率、错得最多的知识点。"""
    from services.question_record_service import daily_summary

    return await daily_summary(db, student_id=current_user.id, days=days)


class FollowupReq(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


@router.post("/v1/questions/ask/{ask_id}/followup")
async def post_ask_followup(
    ask_id: UUID,
    body: FollowupReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_ask_rate_limit),
):
    from services.photo_ask_service import followup_reply

    uid = current_user.id
    rec = await _own_record(db, current_user, ask_id)
    meta = dict(rec.meta or {})
    history = list(meta.get("followups") or [])
    question_text = rec.question_text or ""
    solution = meta.get("solution")
    await db.rollback()
    out = await followup_reply(
        question_text=question_text, solution=solution, history=history, message=body.message
    )
    history.append({"role": "student", "text": body.message[:1000]})
    if out["status"] == "ok":
        history.append({"role": "tutor", "text": out["reply"]})
    from services.question_record_service import update_record

    await update_record(ask_id, uid, meta={"followups": history[-20:]}, understood=False)
    return out


# ── 错题本 ───────────────────────────────────────────────────────────────────


class WrongbookAddReq(BaseModel):
    record_id: UUID


@router.post("/v1/wrongbook/add")
async def post_wrongbook_add(
    body: WrongbookAddReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.question_record_service import add_record_to_wrong_book

    out = await add_record_to_wrong_book(db, student_id=current_user.id, record_id=body.record_id)
    if out is None:
        await db.rollback()
        raise HTTPException(status_code=404, detail="题目不存在")
    if out.get("error") == "empty_question":
        await db.rollback()
        raise HTTPException(status_code=422, detail="这道题还没有题目文字，先确认题目再加入错题本")
    return out


# ── 做题记录 ─────────────────────────────────────────────────────────────────


@router.get("/v1/questions/history")
async def get_history(
    subject: Optional[str] = Query(None, max_length=20),
    source: Optional[str] = Query(None, max_length=32),
    result: Optional[Literal["correct", "wrong", "unknown"]] = Query(None),
    since: Optional[date] = Query(None),
    until: Optional[date] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.question_record_service import list_history

    return await list_history(
        db,
        student_id=current_user.id,
        subject=subject or None,
        source=source or None,
        result=result,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


@router.get("/v1/questions/history/{record_id}")
async def get_history_item(
    record_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.question_record_service import get_record

    out = await get_record(db, student_id=current_user.id, record_id=record_id)
    if out is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return out


@router.get("/v1/questions/records/{record_id}/image")
async def get_record_image(
    record_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.photo_ask_service import sniff_image
    from services.question_record_service import record_image_key

    key = await record_image_key(db, student_id=current_user.id, record_id=record_id)
    if not key:
        raise HTTPException(status_code=404, detail="没有图片")
    try:
        from services.storage import download_question_image

        data = await asyncio.to_thread(download_question_image, key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="没有图片") from exc
    return Response(
        content=data,
        media_type=sniff_image(data) or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=300"},
    )


# ── 10 分钟错题复习 ─────────────────────────────────────────────────────────


@router.get("/v1/review/today")
async def get_review_today(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from zoneinfo import ZoneInfo

    from services.question_record_service import review_streak
    from services.wrongbook_review_service import build_today_session

    session = await build_today_session(db, current_user.id)
    today = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).date()
    st = await review_streak(db, student_id=current_user.id, today=today)
    return {**session, "streak": st["streak"]}


class ReviewAnswerReq(BaseModel):
    session_id: Optional[str] = Field(default=None, max_length=64)
    item_id: UUID
    answer: str = Field(default="", max_length=2000)
    duration_ms: Optional[int] = Field(default=None, ge=0, le=3_600_000)
    self_grade: Optional[bool] = None


@router.post("/v1/review/today/answer")
async def post_review_today_answer(
    body: ReviewAnswerReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.wrongbook_review_service import answer_item

    out = await answer_item(
        db,
        current_user.id,
        item_id=body.item_id,
        answer=body.answer,
        duration_ms=body.duration_ms,
        self_grade=body.self_grade,
        session_id=body.session_id,
    )
    if out is None:
        raise HTTPException(status_code=404, detail="错题不存在")
    return out


class ReviewFinishReq(BaseModel):
    session_id: Optional[str] = Field(default=None, max_length=64)
    answered: int = Field(default=0, ge=0, le=100)
    correct: int = Field(default=0, ge=0, le=100)
    duration_seconds: Optional[int] = Field(default=None, ge=0, le=36000)


@router.post("/v1/review/today/finish")
async def post_review_today_finish(
    body: ReviewFinishReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.wrongbook_review_service import finish_session

    return await finish_session(
        db, current_user.id, answered=body.answered, correct=min(body.correct, body.answered)
    )
