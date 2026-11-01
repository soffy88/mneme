"""分级有声路由（Parroto 分级有声＋逐词高亮的方法，干净重写）。

鉴权与可见性纪律照搬 teaching_figures：admin 创建/验证；学生仅见
verified；未验证对非 admin 一律 404。组装只返回播放数据（分句＋词级
时间码原样透传，无对齐时不编造时间码）；不做请求时 TTS/STT 合成，
音频由既有管线离线产出。用户可见字符串走 t()。
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
from services.graded_audio import assemble_graded_audio, verify_graded_audio_spec
from services.i18n import negotiate_language, t
from services.models import GradedAudioSpec, ReadingPassage, User

router = APIRouter(prefix="/v1/graded-audio", tags=["graded-audio"])


def _lang(accept_language: Optional[str], lang: Optional[str]) -> str:
    return negotiate_language(accept_language, lang)


def _view(row: GradedAudioSpec) -> dict[str, Any]:
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
                "message": t("graded_audio.gate_failed", lg),
                "issues": [
                    {
                        "field": "passage_id",
                        "code": "unknown_passage",
                        "message": "passage_id does not exist",
                    }
                ],
            },
        )
    gates, issues = verify_graded_audio_spec(spec, passage_text)
    if not (all(gates.values()) and not issues):
        raise HTTPException(
            status_code=422,
            detail={
                "message": t("graded_audio.gate_failed", lg),
                "issues": [issue.to_dict() for issue in issues],
            },
        )


async def _visible_row(
    db: AsyncSession, spec_id: str, current_user: User, lg: str
) -> GradedAudioSpec:
    row = await db.get(GradedAudioSpec, spec_id)
    if row is None or (not row.verified and not is_admin(current_user)):
        raise HTTPException(status_code=404, detail=t("common.not_found", lg))
    return row


@router.post("/specs")
async def create_graded_audio_spec(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403, detail=t("graded_audio.create_forbidden", lg)
        )
    spec = payload.get("spec")
    if not isinstance(spec, dict) or not isinstance(spec.get("id"), str) or not spec["id"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": t("graded_audio.gate_failed", lg),
                "issues": [
                    {
                        "field": "spec.id",
                        "code": "missing_id",
                        "message": "spec.id must be a non-empty string",
                    }
                ],
            },
        )
    if await db.get(GradedAudioSpec, spec["id"]) is not None:
        raise HTTPException(
            status_code=409, detail=t("graded_audio.duplicate_id", lg)
        )
    source = spec.get("source")
    passage_ref = source.get("passage_id") if isinstance(source, dict) else None
    passage_missing = isinstance(passage_ref, str) and passage_ref and (
        await _passage_text(db, spec) is None
    )
    _gate_or_422(spec, await _passage_text(db, spec), bool(passage_missing), lg)
    row = GradedAudioSpec(
        id=spec["id"], spec=spec, verified=False, author_id=current_user.id
    )
    db.add(row)
    await db.flush()
    view = _view(row)
    await db.commit()
    return view


@router.get("/specs")
async def list_graded_audio_specs(
    include_unverified: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    _lang(accept_language, lang)
    stmt = select(GradedAudioSpec).order_by(GradedAudioSpec.created_at)
    if not (include_unverified and is_admin(current_user)):
        stmt = stmt.where(GradedAudioSpec.verified.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_view(row) for row in rows]}


@router.get("/specs/{spec_id}")
async def get_graded_audio_spec(
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
async def verify_graded_audio_spec_endpoint(
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403, detail=t("graded_audio.verify_forbidden", lg)
        )
    row = await db.get(GradedAudioSpec, spec_id)
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


@router.get("/specs/{spec_id}/assemble")
async def assemble_graded_audio_endpoint(
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    row = await _visible_row(db, spec_id, current_user, lg)
    source = row.spec.get("source")
    passage_ref = source.get("passage_id") if isinstance(source, dict) else None
    passage_missing = isinstance(passage_ref, str) and passage_ref and (
        await _passage_text(db, row.spec) is None
    )
    _gate_or_422(row.spec, await _passage_text(db, row.spec), bool(passage_missing), lg)
    return assemble_graded_audio(row.spec)
