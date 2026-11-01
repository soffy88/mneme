"""物理计算题项路由（学生本人，需登录；创建/验证仅 admin）。

- POST /v1/physics-practice            创建题项（admin；verified 恒 False）
- GET  /v1/physics-practice            列表（学生仅见 verified；admin 可看全部）
- GET  /v1/physics-practice/{item_id}  详情（未 verified 的仅 admin 可见）
- POST /v1/physics-practice/{item_id}/verify  服务端重跑门禁，全过才置 verified

verified 只由 verify 端点重跑门禁后设置；创建与其它写路径一律不
接受客户端的 verified 输入。题项答案永不信任客户端写入：创建与
验证都由服务端按模型重算核对。
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
from services.models import KnowledgeUnit, PhysicsPracticeItem, User
from services.physics_practice import verify_practice_item

router = APIRouter(prefix="/v1/physics-practice", tags=["physics-practice"])


class PhysicsPracticeCreate(BaseModel):
    spec: dict


def _public_dict(row: PhysicsPracticeItem) -> dict:
    return {
        "id": row.id,
        "model_id": row.model_id,
        "spec": row.spec,
        "verified": row.verified,
        "author_id": str(row.author_id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _get_or_404(db: AsyncSession, item_id: str) -> PhysicsPracticeItem:
    row = await db.get(PhysicsPracticeItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="物理计算题项不存在")
    return row


@router.post("")
async def create_physics_practice_item(
    payload: PhysicsPracticeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="仅 admin 可创建物理计算题项")
    spec = payload.spec
    spec_id = spec.get("id") if isinstance(spec, dict) else None
    if isinstance(spec_id, str):
        if await db.get(PhysicsPracticeItem, spec_id) is not None:
            raise HTTPException(status_code=409, detail=f"题项 id {spec_id!r} 已存在")
    ku = None
    if isinstance(spec, dict) and isinstance(spec.get("ku_id"), str):
        ku = await db.get(KnowledgeUnit, spec["ku_id"])
    result = verify_practice_item(
        spec, known_ku_ids={ku.id} if ku is not None else set()
    )
    if not result.passed:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "题项未通过验证门",
                "issues": [vars(i) for i in result.issues],
                "gates": result.gates,
            },
        )
    model_name = spec.get("model") if isinstance(spec, dict) else None
    row = PhysicsPracticeItem(
        id=spec_id, model_id=model_name, spec=spec,
        verified=False, author_id=current_user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _public_dict(row)


@router.get("")
async def list_physics_practice_items(
    model_id: Optional[str] = Query(default=None),
    include_unverified: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    admin = is_admin(current_user)
    stmt = select(PhysicsPracticeItem).order_by(PhysicsPracticeItem.id)
    if model_id:
        stmt = stmt.where(PhysicsPracticeItem.model_id == model_id)
    if not (admin and include_unverified):
        stmt = stmt.where(PhysicsPracticeItem.verified.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_public_dict(r) for r in rows], "total": len(rows)}


@router.get("/{item_id}")
async def get_physics_practice_item(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _get_or_404(db, item_id)
    if not row.verified and not is_admin(current_user):
        raise HTTPException(status_code=404, detail="物理计算题项不存在")
    return _public_dict(row)


@router.post("/{item_id}/verify")
async def verify_physics_practice_item(
    item_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="仅 admin 可验证物理计算题项")
    row = await _get_or_404(db, item_id)
    ku = None
    if isinstance(row.spec, dict) and isinstance(row.spec.get("ku_id"), str):
        ku = await db.get(KnowledgeUnit, row.spec["ku_id"])
    result = verify_practice_item(
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
                "message": "题项未通过验证门",
                "issues": [vars(i) for i in result.issues],
                "gates": result.gates,
            },
        )
    return _public_dict(row)
