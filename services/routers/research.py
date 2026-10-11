"""研究报告路由（DeepTutor「Deep Research」儿童安全版）。

- POST /v1/research          发起一次研究（学生本人 / admin），同步返回报告
- GET  /v1/research          本人的研究记录（新→旧）+ 今日额度
- GET  /v1/research/{id}     本人的一份报告（别人的 id → 404）

只检索本地教材库，不联网；每条论断引用 书/页/切片。业务逻辑在
services/research_service.py，路由只做鉴权与 HTTP 映射。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from obase.db import get_db
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import get_current_user
from services.models import User, UserRole

router = APIRouter(tags=["research"])


class ResearchReq(BaseModel):
    question: str = Field(..., min_length=1, max_length=400)
    persona_slug: Optional[str] = Field(default=None, max_length=64)


def _is_admin(user: User) -> bool:
    from obase.admin_identity import is_admin

    return is_admin(user)


def _ensure_researcher(user: User) -> bool:
    """学生本人或 admin；家长账号只读不消耗孩子的额度（同 books 入口口径）。"""
    admin = _is_admin(user)
    if not admin and user.role != UserRole.student:
        raise HTTPException(status_code=403, detail="仅学生本人或管理员可以使用研究功能")
    return admin


@router.post("/v1/research", status_code=201)
async def create_research(
    req: ResearchReq,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from services import research_service as svc

    admin = _ensure_researcher(current_user)
    try:
        return await svc.create_research(
            db,
            student_id=str(current_user.id),
            question=req.question,
            grade=current_user.grade,
            persona_slug=req.persona_slug,
            is_admin=admin,
        )
    except svc.ResearchRejected as rej:
        raise HTTPException(status_code=rej.status_code, detail=rej.detail) from None


@router.get("/v1/research")
async def list_research(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from services import research_service as svc

    _ensure_researcher(current_user)
    return await svc.list_research(db, student_id=str(current_user.id), limit=limit)


@router.get("/v1/research/{research_id}")
async def get_research(
    research_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from services import research_service as svc

    _ensure_researcher(current_user)
    got = await svc.get_research(db, research_id, student_id=str(current_user.id))
    if got is None:
        raise HTTPException(status_code=404, detail="research not found")
    return got
