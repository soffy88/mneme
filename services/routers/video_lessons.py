"""视频课规格路由（DeepTutor 视频课循环的方法，干净重写）。

鉴权与可见性纪律照搬 services/routers/teaching_figures.py：admin 创建/
验证；学生仅见 verified；未验证规格对非 admin 一律 404；verified 恒由
服务端门禁设置，客户端传入的 verified 一律忽略。用户可见字符串走
services/i18n.py 的 t()。本路由只做规格的创建/验证/组装：不生成
媒体、不调 LLM、不做请求时 TTS。
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
from services.models import KnowledgeUnit, User, VideoLessonSpec
from services.video_lesson import (
    VideoLessonCheck,
    assemble_video_lesson,
    verify_video_lesson,
)

router = APIRouter(prefix="/v1/video-lessons", tags=["video-lessons"])


def _lang(accept_language: Optional[str], lang: Optional[str]) -> str:
    return negotiate_language(accept_language, lang)


def _view(row: VideoLessonSpec) -> dict[str, Any]:
    return {
        "id": row.id,
        "ku_id": row.ku_id,
        "spec": row.spec,
        "verified": bool(row.verified),
        "author_id": str(row.author_id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _known_ku_ids(db: AsyncSession) -> set[str]:
    return set(await db.scalars(select(KnowledgeUnit.id)))


def _gate_or_422(spec: dict, known: set[str], lg: str) -> None:
    check: VideoLessonCheck = verify_video_lesson(spec, known)
    if not check.passed:
        raise HTTPException(
            status_code=422,
            detail={
                "message": t("video_lesson.gate_failed", lg),
                "issues": [issue.to_dict() for issue in check.issues],
            },
        )


async def _visible_row(
    db: AsyncSession, spec_id: str, current_user: User, lg: str
) -> VideoLessonSpec:
    row = await db.get(VideoLessonSpec, spec_id)
    if row is None or (not row.verified and not is_admin(current_user)):
        raise HTTPException(
            status_code=404, detail=t("common.not_found", lg)
        )
    return row


@router.post("")
async def create_video_lesson(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403, detail=t("video_lesson.create_forbidden", lg)
        )
    spec = payload.get("spec")
    if not isinstance(spec, dict) or not isinstance(spec.get("id"), str) or not spec["id"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": t("video_lesson.gate_failed", lg),
                "issues": [
                    {
                        "field": "spec.id",
                        "code": "missing_id",
                        "message": "spec.id must be a non-empty string",
                    }
                ],
            },
        )
    if await db.get(VideoLessonSpec, spec["id"]) is not None:
        raise HTTPException(
            status_code=409, detail=t("video_lesson.duplicate_id", lg)
        )
    _gate_or_422(spec, await _known_ku_ids(db), lg)
    ku_id = spec.get("ku_id")
    row = VideoLessonSpec(
        id=spec["id"],
        ku_id=ku_id if isinstance(ku_id, str) else None,
        spec=spec,
        verified=False,
        author_id=current_user.id,
    )
    db.add(row)
    await db.flush()
    view = _view(row)
    await db.commit()
    return view


@router.get("")
async def list_video_lessons(
    include_unverified: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    _lang(accept_language, lang)
    stmt = select(VideoLessonSpec).order_by(VideoLessonSpec.created_at)
    if not (include_unverified and is_admin(current_user)):
        stmt = stmt.where(VideoLessonSpec.verified.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_view(row) for row in rows]}


@router.get("/{spec_id}")
async def get_video_lesson(
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    row = await _visible_row(db, spec_id, current_user, lg)
    return _view(row)


@router.post("/{spec_id}/verify")
async def verify_video_lesson_endpoint(
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    if not is_admin(current_user):
        raise HTTPException(
            status_code=403, detail=t("video_lesson.verify_forbidden", lg)
        )
    row = await db.get(VideoLessonSpec, spec_id)
    if row is None:
        raise HTTPException(status_code=404, detail=t("common.not_found", lg))
    _gate_or_422(row.spec, await _known_ku_ids(db), lg)
    row.verified = True
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    view = _view(row)
    await db.commit()
    return view


@router.get("/{spec_id}/assemble")
async def assemble_video_lesson_endpoint(
    spec_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    row = await _visible_row(db, spec_id, current_user, lg)
    _gate_or_422(row.spec, await _known_ku_ids(db), lg)
    return assemble_video_lesson(row.spec)
