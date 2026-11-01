"""听写路由（Parroto 听写环的方法，干净重写）。

鉴权与可见性纪律照搬 teaching_figures：admin 创建/验证；学生仅见
verified；未验证对非 admin 一律 404。尝试只追加：成绩与错词落
DictationAttempt，错词同时以 QuestionRecord 行追加（source="dictation"，
只追加、不写 BKT/FSRS 到 WrongQuestion）；排期走 detached FSRS 卡，
不碰任何 WrongQuestion 行。音频/原文永不入库，原文以 passage_id 溯源。
用户可见字符串走 t()。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from obase.admin_identity import is_admin
from obase.db import get_db
from services.auth_deps import get_current_user
from services.dictation import (
    compute_dictation_schedule,
    grade_dictation,
    self_written_passages,
    verify_dictation_spec,
)
from services.i18n import negotiate_language, t
from services.models import (
    DictationAttempt,
    DictationSpec,
    QuestionRecord,
    ReadingPassage,
    User,
)

router = APIRouter(prefix="/v1/dictation", tags=["dictation"])


def _lang(accept_language: Optional[str], lang: Optional[str]) -> str:
    return negotiate_language(accept_language, lang)


def _view(row: DictationSpec) -> dict[str, Any]:
    return {
        "id": row.id,
        "spec": row.spec,
        "verified": bool(row.verified),
        "author_id": str(row.author_id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _passage_text(db: AsyncSession, spec: dict) -> Optional[str]:
    source = spec.get("source")
    passage_id = source.get("passage_id") if isinstance(source, dict) else None
    if not isinstance(passage_id, str) or not passage_id:
        return None
    row = await db.get(ReadingPassage, passage_id)
    return row.body_text if row is not None else None


def _gate_or_422(
    spec: dict, passage_text: Optional[str], passage_missing: bool, lg: str
) -> None:
    if passage_missing:
        raise HTTPException(
            status_code=422,
            detail={
                "message": t("dictation.gate_failed", lg),
                "issues": [
                    {
                        "field": "passage_id",
                        "code": "unknown_passage",
                        "message": "passage_id does not exist",
                    }
                ],
            },
        )
    gates, issues = verify_dictation_spec(spec, passage_text)
    if not (all(gates.values()) and not issues):
        raise HTTPException(
            status_code=422,
            detail={
                "message": t("dictation.gate_failed", lg),
                "issues": [issue.to_dict() for issue in issues],
            },
        )


async def _visible_row(
    db: AsyncSession, spec_id: str, current_user: User, lg: str
) -> DictationSpec:
    row = await db.get(DictationSpec, spec_id)
    if row is None or (not row.verified and not is_admin(current_user)):
        raise HTTPException(status_code=404, detail=t("common.not_found", lg))
    return row


@router.get("/passages")
async def list_self_written_passages(
    current_user: User = Depends(get_current_user),
) -> dict:
    return {"items": self_written_passages()}


@router.post("/specs")
async def create_dictation_spec(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403, detail=t("dictation.create_forbidden", lg)
        )
    spec = payload.get("spec")
    if not isinstance(spec, dict) or not isinstance(spec.get("id"), str) or not spec["id"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": t("dictation.gate_failed", lg),
                "issues": [
                    {
                        "field": "spec.id",
                        "code": "missing_id",
                        "message": "spec.id must be a non-empty string",
                    }
                ],
            },
        )
    if await db.get(DictationSpec, spec["id"]) is not None:
        raise HTTPException(
            status_code=409, detail=t("dictation.duplicate_id", lg)
        )
    source = spec.get("source")
    passage_ref = source.get("passage_id") if isinstance(source, dict) else None
    passage_missing = isinstance(passage_ref, str) and passage_ref and (
        await _passage_text(db, spec) is None
    )
    _gate_or_422(spec, await _passage_text(db, spec), bool(passage_missing), lg)
    row = DictationSpec(
        id=spec["id"], spec=spec, verified=False, author_id=current_user.id
    )
    db.add(row)
    await db.flush()
    view = _view(row)
    await db.commit()
    return view


@router.get("/specs")
async def list_dictation_specs(
    include_unverified: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    _lang(accept_language, lang)
    stmt = select(DictationSpec).order_by(DictationSpec.created_at)
    if not (include_unverified and is_admin(current_user)):
        stmt = stmt.where(DictationSpec.verified.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_view(row) for row in rows]}


@router.get("/specs/{spec_id}")
async def get_dictation_spec(
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    row = await _visible_row(db, spec_id, current_user, lg)
    return _view(row)


@router.post("/specs/{spec_id}/verify")
async def verify_dictation_spec_endpoint(
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403, detail=t("dictation.verify_forbidden", lg)
        )
    row = await db.get(DictationSpec, spec_id)
    if row is None:
        raise HTTPException(status_code=404, detail=t("common.not_found", lg))
    source = row.spec.get("source")
    passage_ref = source.get("passage_id") if isinstance(source, dict) else None
    passage_missing = isinstance(passage_ref, str) and passage_ref and (
        await _passage_text(db, row.spec) is None
    )
    _gate_or_422(row.spec, await _passage_text(db, row.spec), bool(passage_missing), lg)
    row.verified = True
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    view = _view(row)
    await db.commit()
    return view


@router.post("/specs/{spec_id}/attempts")
async def submit_dictation_attempt(
    spec_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    row = await _visible_row(db, spec_id, current_user, lg)
    typed_text = payload.get("typed_text")
    if not isinstance(typed_text, str):
        raise HTTPException(
            status_code=422,
            detail={
                "message": t("dictation.gate_failed", lg),
                "issues": [
                    {
                        "field": "typed_text",
                        "code": "missing_typed_text",
                        "message": "typed_text must be a string",
                    }
                ],
            },
        )
    segments = row.spec.get("segments") or []
    grade = grade_dictation(segments, typed_text)
    previous = (
        await db.execute(
            select(DictationAttempt)
            .where(DictationAttempt.student_id == current_user.id)
            .where(DictationAttempt.spec_id == spec_id)
            .order_by(DictationAttempt.created_at.desc())
        )
    ).scalars().first()
    card, due = compute_dictation_schedule(
        all_correct=bool(grade["score"] >= 1.0),
        previous_card=(previous.fsrs_card_json if previous is not None else None),
    )
    attempt = DictationAttempt(
        student_id=current_user.id,
        spec_id=spec_id,
        score=float(grade["score"]),
        missed_words=list(grade["missed_words"]),
        fsrs_card_json=card,
        fsrs_due=due,
    )
    db.add(attempt)
    await db.flush()
    attempt_id = attempt.id
    subject = row.spec.get("subject") or "english"
    for word in grade["missed_words"]:
        db.add(
            QuestionRecord(
                student_id=current_user.id,
                source="dictation",
                subject=subject,
                question_text=word,
                student_answer=None,
                correct_answer=word,
                is_correct=False,
                grader="dictation",
                wrong_question_id=None,
                meta={"spec_id": spec_id, "attempt_id": str(attempt_id)},
            )
        )
    await db.commit()
    return {
        "attempt_id": str(attempt_id),
        "spec_id": spec_id,
        "score": grade["score"],
        "correct": grade["correct"],
        "total": grade["total"],
        "segments": grade["segments"],
        "missed_words": grade["missed_words"],
        "fsrs_due": due.isoformat(),
    }


@router.get("/specs/{spec_id}/attempts")
async def list_dictation_attempts(
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    await _visible_row(db, spec_id, current_user, lg)
    stmt = (
        select(DictationAttempt)
        .where(DictationAttempt.spec_id == spec_id)
        .order_by(DictationAttempt.created_at.desc())
    )
    if not is_admin(current_user):
        stmt = stmt.where(DictationAttempt.student_id == current_user.id)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": str(attempt.id),
                "student_id": str(attempt.student_id),
                "spec_id": attempt.spec_id,
                "score": attempt.score,
                "missed_words": attempt.missed_words,
                "fsrs_due": attempt.fsrs_due.isoformat() if attempt.fsrs_due else None,
                "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
            }
            for attempt in rows
        ]
    }
