"""统一做题记录（question_records）+ 错题本入口。

产品诉求「学生的每个题目都要记录」：学生见到/作答的每一道题都落一行 question_records，
来源（source）区分拍照提问、练习、小测、复习、对话等。

红线：
- **记录失败绝不打断主流程**。所有写入走独立 DB 会话（不搭主事务，主事务回滚/提交都不受影响），
  异常只记 warning（不含题干/作答等儿童数据），返回 None。
- 只追加：不删、不改题目事实；只回填关联/反馈列（见 models.QuestionRecord）。
- 日志不写 PII：只记 source 与异常类型。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.logging_config import logger
from services.models import QuestionRecord, WrongQuestion

# 来源白名单与中文标签（history 页筛选/徽标用）。未知来源一律记 "other"。
SOURCE_LABELS: dict[str, str] = {
    "photo_ask": "拍照提问",
    "practice": "练习",
    "quiz": "小测",
    "review": "错题复习",
    "kc_review": "知识点复习",
    "mcp": "练习/对话",
    "chat": "对话",
    "socratic": "引导对话",
    "solver": "解题工具",
    "paper": "试卷",
    "book": "书本",
    "lab": "实验",
    "manual": "手动添加",
    "other": "其他",
}
GRADERS = {"kernel", "rule", "llm", "self", "none"}

_MAX_TEXT = 8000
_MAX_ANSWER = 4000


def source_label(source: Optional[str]) -> str:
    return SOURCE_LABELS.get(source or "other", SOURCE_LABELS["other"])


def _clip(value: Optional[str], limit: int) -> Optional[str]:
    if value is None:
        return None
    s = str(value)
    return s if len(s) <= limit else s[:limit]


def _norm_kc_ids(kc_ids: Any) -> Optional[list[str]]:
    if kc_ids is None:
        return None
    if isinstance(kc_ids, str):
        items: Iterable[Any] = [kc_ids]
    elif isinstance(kc_ids, dict):
        items = kc_ids.keys()
    else:
        items = kc_ids
    out = [str(k) for k in items if k and str(k) != "unknown"]
    return out[:20] or None


def _session_factory() -> Any:
    from obase.db import SessionLocal

    return SessionLocal


async def record_question(
    *,
    student_id: Optional[uuid.UUID],
    source: str,
    question_text: Optional[str],
    subject: Optional[str] = None,
    grade: Optional[str] = None,
    kc_ids: Any = None,
    question_ref: Optional[str] = None,
    image_key: Optional[str] = None,
    student_answer: Optional[str] = None,
    correct_answer: Optional[str] = None,
    is_correct: Optional[bool] = None,
    grader: Optional[str] = None,
    hints_used: int = 0,
    duration_ms: Optional[int] = None,
    wrong_question_id: Optional[uuid.UUID] = None,
    auto_wrong_book: bool = False,
    meta: Optional[dict] = None,
) -> Optional[uuid.UUID]:
    """落一条做题记录（独立会话、自提交）。失败返回 None，永不抛。

    auto_wrong_book=True 且答错、调用方没给 wrong_question_id 时，顺带把题加入错题本
    （同一学生同一题干未毕业的错题只留一条，见 add_to_wrong_book）。
    """
    if not isinstance(student_id, uuid.UUID):
        return None  # 未登录/测试替身用户：无从归属，不记
    try:
        src = source if source in SOURCE_LABELS else "other"
        g = grader if grader in GRADERS else (None if grader is None else "rule")
        async with _session_factory()() as db:
            wq_id = wrong_question_id
            if (
                auto_wrong_book
                and is_correct is False
                and wq_id is None
                and (question_text or "").strip()
            ):
                wq_id = await _ensure_wrong_question(
                    db,
                    student_id=student_id,
                    source=src,
                    subject=subject,
                    question_text=question_text or "",
                    student_answer=student_answer,
                    correct_answer=correct_answer,
                    kc_ids=kc_ids,
                    image_key=image_key,
                )
            rid = uuid.uuid4()
            rec = QuestionRecord(
                id=rid,
                student_id=student_id,
                source=src,
                subject=_clip(subject, 20),
                grade=_clip(grade, 10),
                kc_ids=_norm_kc_ids(kc_ids),
                question_ref=_clip(question_ref, 128),
                question_text=_clip(question_text, _MAX_TEXT),
                image_key=image_key,
                student_answer=_clip(student_answer, _MAX_ANSWER),
                correct_answer=_clip(correct_answer, _MAX_ANSWER),
                is_correct=is_correct,
                grader=g,
                hints_used=max(0, int(hints_used or 0)),
                duration_ms=int(duration_ms) if duration_ms is not None else None,
                wrong_question_id=wq_id,
                meta=meta,
            )
            db.add(rec)
            if wq_id is not None:
                wq = await db.get(WrongQuestion, wq_id)
                if wq is not None and wq.question_record_id is None:
                    wq.question_record_id = rid
            await db.commit()
            return rid
    except Exception as exc:  # noqa: BLE001 — 记录是旁路，绝不打断主流程
        logger.warning("question_record write failed (source=%s): %s", source, type(exc).__name__)
        return None


async def update_record(record_id: uuid.UUID, student_id: uuid.UUID, **fields: Any) -> bool:
    """回填关联/反馈列（独立会话）。只允许白名单列；失败返回 False，永不抛。"""
    allowed = {
        "question_text",
        "subject",
        "grade",
        "understood",
        "hints_used",
        "wrong_question_id",
        "correct_answer",
        "meta",
        "duration_ms",
    }
    try:
        async with _session_factory()() as db:
            rec = await db.get(QuestionRecord, record_id)
            if rec is None or rec.student_id != student_id:
                return False
            for k, v in fields.items():
                if k not in allowed:
                    continue
                if k == "meta" and isinstance(v, dict):
                    merged = dict(rec.meta or {})
                    merged.update(v)
                    rec.meta = merged
                elif k == "question_text":
                    rec.question_text = _clip(v, _MAX_TEXT)
                else:
                    setattr(rec, k, v)
            rec.updated_at = datetime.now(timezone.utc)
            await db.commit()
            return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("question_record update failed: %s", type(exc).__name__)
        return False


def _text_key(text: str) -> str:
    norm = "".join((text or "").split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


async def _ensure_wrong_question(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    source: str,
    subject: Optional[str],
    question_text: str,
    student_answer: Optional[str],
    correct_answer: Optional[str],
    kc_ids: Any,
    image_key: Optional[str],
) -> uuid.UUID:
    """同一学生、同一题干（忽略空白）、尚未毕业的错题只保留一条；没有则新建。

    已有则把它重新排进复习（fsrs_due=now、连对清零）——又错一次说明还没掌握。
    """
    key = _text_key(question_text)
    rows = (
        await db.execute(
            select(WrongQuestion).where(
                WrongQuestion.student_id == student_id,
                WrongQuestion.graduated_at.is_(None),
            )
            .order_by(WrongQuestion.created_at.desc())
            .limit(500)
        )
    ).scalars().all()
    for wq in rows:
        if _text_key(wq.question_text or "") == key:
            if student_answer:
                wq.student_answer = _clip(student_answer, _MAX_ANSWER)
            if correct_answer and not wq.correct_answer:
                wq.correct_answer = _clip(correct_answer, _MAX_ANSWER)
            wq.review_correct_streak = 0
            wq.fsrs_due = datetime.now(timezone.utc)
            await db.flush()
            return wq.id
    kcs = _norm_kc_ids(kc_ids)
    wq = WrongQuestion(
        id=uuid.uuid4(),
        student_id=student_id,
        subject=_clip(subject, 20) or None,
        question_text=_clip(question_text, _MAX_TEXT),
        student_answer=_clip(student_answer, _MAX_ANSWER),
        correct_answer=_clip(correct_answer, _MAX_ANSWER),
        knowledge_points={k: k for k in kcs} if kcs else None,
        source=source,
        image_key=image_key,
        needs_image=False,
    )
    db.add(wq)
    await db.flush()
    return wq.id


async def add_record_to_wrong_book(
    db: AsyncSession, *, student_id: uuid.UUID, record_id: uuid.UUID
) -> Optional[dict]:
    """「加入错题本」一键：按记录建/复用错题，并回填记录的 wrong_question_id。

    返回 {wrong_question_id, created}；记录不存在或不属于该生 → None。
    """
    rec = await db.get(QuestionRecord, record_id)
    if rec is None or rec.student_id != student_id:
        return None
    if rec.wrong_question_id is not None:
        existing = await db.get(WrongQuestion, rec.wrong_question_id)
        if existing is not None and existing.graduated_at is None:
            return {"wrong_question_id": str(existing.id), "created": False}
    if not (rec.question_text or "").strip():
        return {"error": "empty_question"}
    before = (
        await db.execute(
            select(func.count()).select_from(WrongQuestion).where(WrongQuestion.student_id == student_id)
        )
    ).scalar_one()
    wq_id = await _ensure_wrong_question(
        db,
        student_id=student_id,
        source="manual" if rec.source != "photo_ask" else "photo_ask",
        subject=rec.subject,
        question_text=rec.question_text or "",
        student_answer=rec.student_answer,
        correct_answer=rec.correct_answer,
        kc_ids=rec.kc_ids,
        image_key=rec.image_key,
    )
    after = (
        await db.execute(
            select(func.count()).select_from(WrongQuestion).where(WrongQuestion.student_id == student_id)
        )
    ).scalar_one()
    rid = rec.id
    rec.wrong_question_id = wq_id
    rec.updated_at = datetime.now(timezone.utc)
    wq = await db.get(WrongQuestion, wq_id)
    if wq is not None and wq.question_record_id is None:
        wq.question_record_id = rid
    await db.commit()
    return {"wrong_question_id": str(wq_id), "created": after > before}


def _serialize(rec: QuestionRecord, *, full: bool) -> dict:
    text = rec.question_text or ""
    base: dict[str, Any] = {
        "id": str(rec.id),
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "source": rec.source,
        "source_label": source_label(rec.source),
        "subject": rec.subject,
        "question_text": text if full else (text[:200] + ("…" if len(text) > 200 else "")),
        "is_correct": rec.is_correct,
        "grader": rec.grader,
        "has_image": bool(rec.image_key),
        "wrong_question_id": str(rec.wrong_question_id) if rec.wrong_question_id else None,
    }
    if full:
        meta = dict(rec.meta or {})
        meta.pop("ocr_raw", None)
        base.update(
            {
                "grade": rec.grade,
                "kc_ids": rec.kc_ids or [],
                "student_answer": rec.student_answer,
                "correct_answer": rec.correct_answer,
                "hints_used": rec.hints_used,
                "duration_ms": rec.duration_ms,
                "understood": rec.understood,
                "meta": meta,
            }
        )
    return base


async def list_history(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    subject: Optional[str] = None,
    source: Optional[str] = None,
    result: Optional[str] = None,
    since: Optional[date] = None,
    until: Optional[date] = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    conds = [QuestionRecord.student_id == student_id]
    if subject:
        conds.append(QuestionRecord.subject == subject)
    if source:
        if source == "other":
            conds.append(
                QuestionRecord.source.notin_(
                    ["photo_ask", "practice", "quiz", "review", "mcp", "chat"]
                )
            )
        else:
            conds.append(QuestionRecord.source == source)
    if result == "correct":
        conds.append(QuestionRecord.is_correct.is_(True))
    elif result == "wrong":
        conds.append(QuestionRecord.is_correct.is_(False))
    elif result == "unknown":
        conds.append(QuestionRecord.is_correct.is_(None))
    if since:
        conds.append(
            QuestionRecord.created_at
            >= datetime(since.year, since.month, since.day, tzinfo=timezone.utc) - timedelta(hours=8)
        )
    if until:
        end = datetime(until.year, until.month, until.day, tzinfo=timezone.utc) + timedelta(days=1)
        conds.append(QuestionRecord.created_at < end - timedelta(hours=8))
    where = and_(*conds)
    total = (
        await db.execute(select(func.count()).select_from(QuestionRecord).where(where))
    ).scalar_one()
    rows = (
        await db.execute(
            select(QuestionRecord)
            .where(where)
            .order_by(QuestionRecord.created_at.desc(), QuestionRecord.id.desc())
            .limit(max(1, min(limit, 100)))
            .offset(max(0, offset))
        )
    ).scalars().all()
    return {"total": int(total), "items": [_serialize(r, full=False) for r in rows]}


async def get_record(
    db: AsyncSession, *, student_id: uuid.UUID, record_id: uuid.UUID
) -> Optional[dict]:
    rec = await db.get(QuestionRecord, record_id)
    if rec is None or rec.student_id != student_id:
        return None
    return _serialize(rec, full=True)


async def record_image_key(
    db: AsyncSession, *, student_id: uuid.UUID, record_id: uuid.UUID
) -> Optional[str]:
    """记录（或其关联错题）的图片键；不属于该生 → None。"""
    rec = await db.get(QuestionRecord, record_id)
    if rec is not None and rec.student_id == student_id:
        return rec.image_key
    wq = await db.get(WrongQuestion, record_id)
    if wq is not None and wq.student_id == student_id:
        return wq.image_key
    return None


async def review_streak(db: AsyncSession, *, student_id: uuid.UUID, today: date) -> dict:
    """错题复习连续天数（按北京时间自然日，取 source=review 的记录）。"""
    since = today - timedelta(days=400)
    local_day = func.date(func.timezone("Asia/Shanghai", QuestionRecord.created_at))
    days = {
        d
        for (d,) in (
            await db.execute(
                select(local_day)
                .where(
                    QuestionRecord.student_id == student_id,
                    QuestionRecord.source == "review",
                    QuestionRecord.created_at
                    >= datetime(since.year, since.month, since.day, tzinfo=timezone.utc),
                )
                .distinct()
            )
        ).all()
    }
    current = 0
    d = today
    if d not in days:
        d = d - timedelta(days=1)  # 今天还没复习，连胜从昨天算起（还没断）
    while d in days:
        current += 1
        d -= timedelta(days=1)
    longest = run = 0
    prev: Optional[date] = None
    for day in sorted(days):
        run = run + 1 if prev is not None and (day - prev).days == 1 else 1
        longest = max(longest, run)
        prev = day
    return {"streak": current, "longest_streak": max(longest, current)}


__all__ = [
    "SOURCE_LABELS",
    "add_record_to_wrong_book",
    "get_record",
    "list_history",
    "record_image_key",
    "record_question",
    "review_streak",
    "source_label",
    "update_record",
]
