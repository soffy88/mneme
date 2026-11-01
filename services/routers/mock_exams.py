"""模考路由（Parroto 全真模考包装的方法，干净重写）。

鉴权与可见性纪律照搬 teaching_figures：admin 创建/验证；学生仅见
verified；未验证对非 admin 一律 404。组装只返回题面（答案永不包含）；
交卷只追加 MockExamAttempt：判分走确定性判分器，不写 BKT/FSRS、
不调 submit_quiz；超时只记 late 位、不改分。用户可见字符串走 t()。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from obase.admin_identity import is_admin
from obase.db import get_db
from services.auth_deps import get_current_user
from services.i18n import negotiate_language, t
from services.mock_exam import (
    assemble_mock_exam,
    score_mock_exam,
    verify_mock_exam_spec,
)
from services.models import MockExamAttempt, MockExamSpec, User, WrongQuestion

router = APIRouter(prefix="/v1/mock-exams", tags=["mock-exams"])


def _lang(accept_language: Optional[str], lang: Optional[str]) -> str:
    return negotiate_language(accept_language, lang)


def _view(row: MockExamSpec) -> dict[str, Any]:
    return {
        "id": row.id,
        "spec": row.spec,
        "verified": bool(row.verified),
        "author_id": str(row.author_id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _spec_question_ids(spec: dict) -> list[str]:
    ids: list[str] = []
    for section in spec.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for qid in section.get("question_ids") or []:
            ids.append(str(qid))
    return ids


async def _existing_question_ids(db: AsyncSession) -> set[str]:
    return {
        str(qid) for qid in await db.scalars(select(WrongQuestion.id))
    }


def _gate_or_422(spec: dict, existing: set[str], lg: str) -> None:
    gates, issues = verify_mock_exam_spec(spec, existing)
    if not (all(gates.values()) and not issues):
        raise HTTPException(
            status_code=422,
            detail={
                "message": t("mock_exam.gate_failed", lg),
                "issues": [issue.to_dict() for issue in issues],
            },
        )


async def _visible_row(
    db: AsyncSession, spec_id: str, current_user: User, lg: str
) -> MockExamSpec:
    row = await db.get(MockExamSpec, spec_id)
    if row is None or (not row.verified and not is_admin(current_user)):
        raise HTTPException(status_code=404, detail=t("common.not_found", lg))
    return row


async def _load_questions(
    db: AsyncSession, ids: list[str], *, with_answers: bool
) -> list[dict[str, Any]]:
    if not ids:
        return []
    uuids: list[uuid.UUID] = []
    for raw in ids:
        try:
            uuids.append(uuid.UUID(str(raw)))
        except (ValueError, TypeError, AttributeError):
            continue
    rows = (
        await db.execute(
            select(WrongQuestion).where(WrongQuestion.id.in_(uuids))
        )
    ).scalars().all()
    by_id = {str(row.id): row for row in rows}
    questions: list[dict[str, Any]] = []
    for qid in ids:
        row = by_id.get(qid)
        if row is None:
            continue
        item: dict[str, Any] = {
            "id": qid,
            "question_text": row.question_text,
            "subject": row.subject,
        }
        if with_answers:
            item["correct_answer"] = row.correct_answer
        questions.append(item)
    return questions


@router.post("/specs")
async def create_mock_exam_spec(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403, detail=t("mock_exam.create_forbidden", lg)
        )
    spec = payload.get("spec")
    if not isinstance(spec, dict) or not isinstance(spec.get("id"), str) or not spec["id"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": t("mock_exam.gate_failed", lg),
                "issues": [
                    {
                        "field": "spec.id",
                        "code": "missing_id",
                        "message": "spec.id must be a non-empty string",
                    }
                ],
            },
        )
    if await db.get(MockExamSpec, spec["id"]) is not None:
        raise HTTPException(
            status_code=409, detail=t("mock_exam.duplicate_id", lg)
        )
    _gate_or_422(spec, await _existing_question_ids(db), lg)
    row = MockExamSpec(
        id=spec["id"], spec=spec, verified=False, author_id=current_user.id
    )
    db.add(row)
    await db.flush()
    view = _view(row)
    await db.commit()
    return view


@router.get("/specs")
async def list_mock_exam_specs(
    include_unverified: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    _lang(accept_language, lang)
    stmt = select(MockExamSpec).order_by(MockExamSpec.created_at)
    if not (include_unverified and is_admin(current_user)):
        stmt = stmt.where(MockExamSpec.verified.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_view(row) for row in rows]}


@router.get("/specs/{spec_id}")
async def get_mock_exam_spec(
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
async def verify_mock_exam_spec_endpoint(
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403, detail=t("mock_exam.verify_forbidden", lg)
        )
    row = await db.get(MockExamSpec, spec_id)
    if row is None:
        raise HTTPException(status_code=404, detail=t("common.not_found", lg))
    _gate_or_422(row.spec, await _existing_question_ids(db), lg)
    row.verified = True
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    view = _view(row)
    await db.commit()
    return view


@router.get("/specs/{spec_id}/assemble")
async def assemble_mock_exam_endpoint(
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    row = await _visible_row(db, spec_id, current_user, lg)
    _gate_or_422(row.spec, await _existing_question_ids(db), lg)
    questions = await _load_questions(
        db, _spec_question_ids(row.spec), with_answers=False
    )
    return assemble_mock_exam(row.spec, questions)


@router.post("/specs/{spec_id}/submit")
async def submit_mock_exam(
    spec_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    row = await _visible_row(db, spec_id, current_user, lg)
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise HTTPException(
            status_code=422, detail=t("mock_exam.answers_mismatch", lg)
        )
    question_ids = _spec_question_ids(row.spec)
    if set(question_ids) != {str(k) for k in answers}:
        raise HTTPException(
            status_code=422, detail=t("mock_exam.answers_mismatch", lg)
        )
    elapsed = payload.get("elapsed_seconds")
    total_seconds = row.spec.get("total_seconds")
    late = (
        isinstance(elapsed, (int, float))
        and not isinstance(elapsed, bool)
        and isinstance(total_seconds, (int, float))
        and elapsed > total_seconds
    )
    questions = await _load_questions(
        db, question_ids, with_answers=True
    )
    result = score_mock_exam(row.spec, questions, answers, late=bool(late))
    attempt = MockExamAttempt(
        student_id=current_user.id,
        spec_id=spec_id,
        answers={str(k): v for k, v in answers.items()},
        result=result,
        late=bool(late),
    )
    db.add(attempt)
    await db.flush()
    attempt_id = attempt.id
    await db.commit()
    return {"attempt_id": str(attempt_id), "spec_id": spec_id, "late": bool(late), "result": result}


@router.get("/specs/{spec_id}/attempts")
async def list_mock_exam_attempts(
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    await _visible_row(db, spec_id, current_user, lg)
    stmt = (
        select(MockExamAttempt)
        .where(MockExamAttempt.spec_id == spec_id)
        .order_by(MockExamAttempt.created_at.desc())
    )
    if not is_admin(current_user):
        stmt = stmt.where(MockExamAttempt.student_id == current_user.id)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": str(attempt.id),
                "student_id": str(attempt.student_id),
                "spec_id": attempt.spec_id,
                "answers": attempt.answers,
                "result": attempt.result,
                "late": bool(attempt.late),
                "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
            }
            for attempt in rows
        ]
    }
