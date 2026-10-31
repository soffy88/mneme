"""教学图规格路由（学生本人，需登录；创建/验证仅 admin）。

- POST /v1/teaching-figures            创建规格（admin；verified 恒 False）
- GET  /v1/teaching-figures            列表（学生仅见 verified；admin 可看全部）
- GET  /v1/teaching-figures/{spec_id}  详情（未 verified 的仅 admin 可见）
- POST /v1/teaching-figures/{spec_id}/verify  服务端重跑门禁，全过才置 verified

verified 只由 verify 端点重跑门禁后设置；创建与其它写路径一律不
接受客户端的 verified 输入。渲染与前端展示不在本次范围（待接点）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from obase.admin_identity import is_admin
from obase.db import get_db
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import get_current_user
from services.models import KnowledgeUnit, TeachingFigureSpec, User
from services.teaching_figure import spec_provenance, verify_figure

router = APIRouter(prefix="/v1/teaching-figures", tags=["teaching-figures"])


class TeachingFigureCreate(BaseModel):
    spec: dict


def _public_dict(
    row: TeachingFigureSpec, textbook_id: Optional[str] = None
) -> dict:
    return {
        "id": row.id,
        "ku_id": row.ku_id,
        "spec": row.spec,
        "verified": row.verified,
        "author_id": str(row.author_id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "provenance": spec_provenance(row.spec, textbook_id=textbook_id),
    }


async def _get_or_404(db: AsyncSession, spec_id: str) -> TeachingFigureSpec:
    row = await db.get(TeachingFigureSpec, spec_id)
    if row is None:
        raise HTTPException(status_code=404, detail="教学图规格不存在")
    return row


@router.post("")
async def create_teaching_figure(
    payload: TeachingFigureCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="仅 admin 可创建教学图规格")
    spec = payload.spec
    spec_id = spec.get("id") if isinstance(spec, dict) else None
    if isinstance(spec_id, str):
        if await db.get(TeachingFigureSpec, spec_id) is not None:
            raise HTTPException(status_code=409, detail=f"规格 id {spec_id!r} 已存在")
    ku = None
    if isinstance(spec, dict) and isinstance(spec.get("ku_id"), str):
        ku = await db.get(KnowledgeUnit, spec["ku_id"])
    # commit 会过期 ORM 属性：先快照，后面只用快照（socratic 修复同款教训）。
    textbook_id = ku.textbook_id if ku else None
    result = verify_figure(
        spec, known_ku_ids={ku.id} if ku is not None else set()
    )
    if not result.passed:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "规格未通过验证门",
                "issues": [vars(i) for i in result.issues],
                "gates": result.gates,
            },
        )
    row = TeachingFigureSpec(
        id=spec_id, ku_id=spec["ku_id"], spec=spec,
        verified=False, author_id=current_user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _public_dict(row, textbook_id=textbook_id)


@router.get("")
async def list_teaching_figures(
    ku_id: Optional[str] = Query(default=None),
    include_unverified: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    admin = is_admin(current_user)
    stmt = select(TeachingFigureSpec).order_by(TeachingFigureSpec.id)
    if ku_id:
        stmt = stmt.where(TeachingFigureSpec.ku_id == ku_id)
    if not (admin and include_unverified):
        stmt = stmt.where(TeachingFigureSpec.verified.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    ku_ids = {r.ku_id for r in rows}
    textbooks = {}
    if ku_ids:
        kus = (
            await db.execute(
                select(KnowledgeUnit).where(KnowledgeUnit.id.in_(ku_ids))
            )
        ).scalars().all()
        textbooks = {k.id: k.textbook_id for k in kus}
    return {
        "items": [_public_dict(r, textbooks.get(r.ku_id)) for r in rows],
        "total": len(rows),
    }


@router.get("/{spec_id}")
async def get_teaching_figure(
    spec_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _get_or_404(db, spec_id)
    if not row.verified and not is_admin(current_user):
        raise HTTPException(status_code=404, detail="教学图规格不存在")
    ku = await db.get(KnowledgeUnit, row.ku_id)
    return _public_dict(row, textbook_id=ku.textbook_id if ku else None)


@router.post("/{spec_id}/verify")
async def verify_teaching_figure(
    spec_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="仅 admin 可验证教学图规格")
    row = await _get_or_404(db, spec_id)
    ku = await db.get(KnowledgeUnit, row.ku_id)
    # commit 会过期 ORM 属性：先快照，后面只用快照。
    textbook_id = ku.textbook_id if ku else None
    result = verify_figure(
        row.spec, known_ku_ids={ku.id} if ku is not None else set()
    )
    row.verified = result.passed
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    if not result.passed:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "规格未通过验证门",
                "issues": [vars(i) for i in result.issues],
                "gates": result.gates,
            },
        )
    return _public_dict(row, textbook_id=textbook_id)
