"""引用核查路由（DeepTutor 数学保义引用核查＋eligibility 门的方法，干净重写）。

无状态核查：调用方提交分段，服务端以库内真实 KU/教材 id 集合逐条
核验引用存在性；数学断言默认不做定性判定（math_unverifiable），不编造
核验结果。eligibility 只读：按既有路径锁拆分可学/不可学 KU，理由原样
返回。用户可见字符串走 services/i18n.py 的 t()。
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from obase.db import get_db
from services.auth_deps import _ensure_student_self, get_current_user
from services.citation_check import check_citations, eligible_review_scope
from services.i18n import negotiate_language, t
from services.models import KnowledgeUnit, Textbook, User

router = APIRouter(prefix="/v1/citation-check", tags=["citation-check"])


def _lang(accept_language: Optional[str], lang: Optional[str]) -> str:
    return negotiate_language(accept_language, lang)


@router.post("/verify")
async def verify_citations(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        raise HTTPException(
            status_code=422, detail=t("citation_check.empty_segments", lg)
        )
    ku_refs: set[str] = set()
    textbook_refs: set[str] = set()
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        refs = segment.get("refs")
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            ref_id = ref.get("id")
            if not isinstance(ref_id, str) or not ref_id:
                continue
            if ref.get("kind") == "ku":
                ku_refs.add(ref_id)
            elif ref.get("kind") == "textbook":
                textbook_refs.add(ref_id)
    known_ku: set[str] = set()
    if ku_refs:
        known_ku = set(
            await db.scalars(
                select(KnowledgeUnit.id).where(KnowledgeUnit.id.in_(ku_refs))
            )
        )
    known_textbook: set[str] = set()
    if textbook_refs:
        known_textbook = set(
            await db.scalars(
                select(Textbook.id).where(Textbook.id.in_(textbook_refs))
            )
        )
    return check_citations(
        segments,
        known_ku_ids=known_ku,
        known_textbook_ids=known_textbook,
    )


@router.post("/eligibility")
async def review_eligibility(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    accept_language: Optional[str] = Header(default=None, alias="Accept-Language"),
    lang: Optional[str] = Query(default=None),
) -> dict:
    lg = _lang(accept_language, lang)
    try:
        student_id = uuid.UUID(str(payload.get("student_id")))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(
            status_code=422, detail=t("citation_check.empty_ku_ids", lg)
        )
    _ensure_student_self(current_user, student_id)
    ku_ids = payload.get("ku_ids")
    if (
        not isinstance(ku_ids, list)
        or not ku_ids
        or not all(isinstance(k, str) and k for k in ku_ids)
    ):
        raise HTTPException(
            status_code=422, detail=t("citation_check.empty_ku_ids", lg)
        )
    return await eligible_review_scope(db, student_id, ku_ids)
