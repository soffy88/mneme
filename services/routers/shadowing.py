"""跟读路由（Parroto 跟读环的方法，干净重写）。

鉴权与可见性纪律照搬 teaching_figures：admin 创建/验证；学生仅见
verified；未验证对非 admin 一律 404。尝试只追加：评分、转写与弱项词
落 ShadowingAttempt；音频只过请求体、永不入库；评分维度只取既有
PronunciationResult 合同（overall/fluency/accuracy/word_scores），
不编造语调/节奏维度。用户可见字符串走 t()。
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
from services.i18n import negotiate_language, t
from services.models import ShadowingAttempt, ShadowingSpec, User
from services.shadowing import score_shadowing, verify_shadowing_spec

router = APIRouter(prefix="/v1/shadowing", tags=["shadowing"])


def _lang(accept_language: Optional[str], lang: Optional[str]) -> str:
    return negotiate_language(accept_language, lang)


def _view(row: ShadowingSpec) -> dict[str, Any]:
    return {
        "id": row.id,
        "spec": row.spec,
        "verified": bool(row.verified),
        "author_id": str(row.author_id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _gate_or_422(spec: dict, lg: str) -> None:
    gates, issues = verify_shadowing_spec(spec)
    if not (all(gates.values()) and not issues):
        raise HTTPException(
            status_code=422,
            detail={
                "message": t("shadowing.gate_failed", lg),
                "issues": [issue.to_dict() for issue in issues],
            },
        )


async def _visible_row(
    db: AsyncSession, spec_id: str, current_user: User, lg: str
) -> ShadowingSpec:
    row = await db.get(ShadowingSpec, spec_id)
    if row is None or (not row.verified and not is_admin(current_user)):
        raise HTTPException(status_code=404, detail=t("common.not_found", lg))
    return row


@router.post("/specs")
async def create_shadowing_spec(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403, detail=t("shadowing.create_forbidden", lg)
        )
    spec = payload.get("spec")
    if not isinstance(spec, dict) or not isinstance(spec.get("id"), str) or not spec["id"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": t("shadowing.gate_failed", lg),
                "issues": [
                    {
                        "field": "spec.id",
                        "code": "missing_id",
                        "message": "spec.id must be a non-empty string",
                    }
                ],
            },
        )
    if await db.get(ShadowingSpec, spec["id"]) is not None:
        raise HTTPException(
            status_code=409, detail=t("shadowing.duplicate_id", lg)
        )
    _gate_or_422(spec, lg)
    row = ShadowingSpec(
        id=spec["id"], spec=spec, verified=False, author_id=current_user.id
    )
    db.add(row)
    await db.flush()
    view = _view(row)
    await db.commit()
    return view


@router.get("/specs")
async def list_shadowing_specs(
    include_unverified: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    _lang(accept_language, lang)
    stmt = select(ShadowingSpec).order_by(ShadowingSpec.created_at)
    if not (include_unverified and is_admin(current_user)):
        stmt = stmt.where(ShadowingSpec.verified.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_view(row) for row in rows]}


@router.get("/specs/{spec_id}")
async def get_shadowing_spec(
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
async def verify_shadowing_spec_endpoint(
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403, detail=t("shadowing.verify_forbidden", lg)
        )
    row = await db.get(ShadowingSpec, spec_id)
    if row is None:
        raise HTTPException(status_code=404, detail=t("common.not_found", lg))
    _gate_or_422(row.spec, lg)
    row.verified = True
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    view = _view(row)
    await db.commit()
    return view


@router.post("/specs/{spec_id}/attempts")
async def submit_shadowing_attempt(
    spec_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    row = await _visible_row(db, spec_id, current_user, lg)
    sentence_index = payload.get("sentence_index")
    sentences = row.spec.get("target_sentences") or []
    if (
        not isinstance(sentence_index, int)
        or isinstance(sentence_index, bool)
        or not 0 <= sentence_index < len(sentences)
    ):
        raise HTTPException(
            status_code=422, detail=t("shadowing.invalid_sentence", lg)
        )
    audio_b64 = payload.get("audio_b64")
    if not isinstance(audio_b64, str) or not audio_b64:
        raise HTTPException(
            status_code=422, detail=t("shadowing.empty_audio", lg)
        )
    reference_text = sentences[sentence_index]
    if not isinstance(reference_text, str) or not reference_text.strip():
        raise HTTPException(
            status_code=422, detail=t("shadowing.invalid_sentence", lg)
        )
    result = await score_shadowing(audio_b64, reference_text)
    attempt = ShadowingAttempt(
        student_id=current_user.id,
        spec_id=spec_id,
        sentence_index=sentence_index,
        scores=result["scores"],
        transcript=result["transcript"],
        weak_words=result["weak_words"],
    )
    db.add(attempt)
    await db.flush()
    attempt_id = attempt.id
    await db.commit()
    return {
        "attempt_id": str(attempt_id),
        "spec_id": spec_id,
        "sentence_index": sentence_index,
        "scores": result["scores"],
        "transcript": result["transcript"],
        "diff": result["diff"],
        "weak_words": result["weak_words"],
    }


@router.get("/specs/{spec_id}/attempts")
async def list_shadowing_attempts(
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    await _visible_row(db, spec_id, current_user, lg)
    stmt = (
        select(ShadowingAttempt)
        .where(ShadowingAttempt.spec_id == spec_id)
        .order_by(ShadowingAttempt.created_at.desc())
    )
    if not is_admin(current_user):
        stmt = stmt.where(ShadowingAttempt.student_id == current_user.id)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": str(attempt.id),
                "student_id": str(attempt.student_id),
                "spec_id": attempt.spec_id,
                "sentence_index": attempt.sentence_index,
                "scores": attempt.scores,
                "transcript": attempt.transcript,
                "weak_words": attempt.weak_words,
                "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
            }
            for attempt in rows
        ]
    }
