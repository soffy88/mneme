"""物理真值模型规格路由（学生本人，需登录；创建/验证仅 admin）。

- POST /v1/physics-models            创建规格（admin；verified 恒 False）
- GET  /v1/physics-models            列表（学生仅见 verified；admin 可看全部）
- GET  /v1/physics-models/{model_id} 详情（未 verified 的仅 admin 可见）
- POST /v1/physics-models/{model_id}/verify  服务端重跑门禁，全过才置 verified
- POST /v1/physics-models/{model_id}/checks  服务端重跑不变量检查（只读）

verified 只由 verify 端点重跑门禁后设置；创建与其它写路径一律不
接受客户端的 verified 输入。3D 渲染与前端展示不在本次范围（待接点，
渲染归 hevi）。模型注册在本模块导入时完成（幂等），见
services.physics_models.register_physics_models。
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
from services.models import KnowledgeUnit, PhysicsModel, User
from services.physics_models import (
    register_physics_models,
    run_invariant_checks,
    verify_physics_model,
)
from services.teaching_figure import spec_provenance

register_physics_models()

router = APIRouter(prefix="/v1/physics-models", tags=["physics-models"])


class PhysicsModelCreate(BaseModel):
    spec: dict


def _public_dict(row: PhysicsModel, textbook_id: Optional[str] = None) -> dict:
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


async def _get_or_404(db: AsyncSession, model_id: str) -> PhysicsModel:
    row = await db.get(PhysicsModel, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="物理模型规格不存在")
    return row


@router.post("")
async def create_physics_model(
    payload: PhysicsModelCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="仅 admin 可创建物理模型规格")
    spec = payload.spec
    spec_id = spec.get("id") if isinstance(spec, dict) else None
    if isinstance(spec_id, str):
        if await db.get(PhysicsModel, spec_id) is not None:
            raise HTTPException(status_code=409, detail=f"规格 id {spec_id!r} 已存在")
    ku = None
    if isinstance(spec, dict) and isinstance(spec.get("ku_id"), str):
        ku = await db.get(KnowledgeUnit, spec["ku_id"])
    # commit 会过期 ORM 属性：先快照，后面只用快照（socratic 修复同款教训）。
    textbook_id = ku.textbook_id if ku else None
    result = verify_physics_model(
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
    row = PhysicsModel(
        id=spec_id, ku_id=spec.get("ku_id") or None, spec=spec,
        verified=False, author_id=current_user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _public_dict(row, textbook_id=textbook_id)


@router.get("")
async def list_physics_models(
    ku_id: Optional[str] = Query(default=None),
    include_unverified: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    admin = is_admin(current_user)
    stmt = select(PhysicsModel).order_by(PhysicsModel.id)
    if ku_id:
        stmt = stmt.where(PhysicsModel.ku_id == ku_id)
    if not (admin and include_unverified):
        stmt = stmt.where(PhysicsModel.verified.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    ku_ids = {r.ku_id for r in rows if r.ku_id}
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


@router.get("/{model_id}")
async def get_physics_model(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _get_or_404(db, model_id)
    if not row.verified and not is_admin(current_user):
        raise HTTPException(status_code=404, detail="物理模型规格不存在")
    ku = await db.get(KnowledgeUnit, row.ku_id) if row.ku_id else None
    return _public_dict(row, textbook_id=ku.textbook_id if ku else None)


@router.post("/{model_id}/verify")
async def verify_physics_model_endpoint(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="仅 admin 可验证物理模型规格")
    row = await _get_or_404(db, model_id)
    ku = await db.get(KnowledgeUnit, row.ku_id) if row.ku_id else None
    # commit 会过期 ORM 属性：先快照，后面只用快照。
    textbook_id = ku.textbook_id if ku else None
    result = verify_physics_model(
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


@router.post("/{model_id}/checks")
async def run_physics_model_checks(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """服务端重跑不变量检查（只读，不改 verified 与任何状态）。"""
    from services.physics_models import PHYSICS_MODEL_REGISTRY

    row = await _get_or_404(db, model_id)
    if not row.verified and not is_admin(current_user):
        raise HTTPException(status_code=404, detail="物理模型规格不存在")
    spec = row.spec
    model_ref = spec.get("model_ref") if isinstance(spec, dict) else None
    model_name = model_ref.get("model") if isinstance(model_ref, dict) else None
    model = PHYSICS_MODEL_REGISTRY.get(model_name) if model_name else None
    if model is None:
        raise HTTPException(
            status_code=422, detail=f"unknown physics model: {model_name!r}"
        )
    params = model_ref.get("parameters")
    if not isinstance(params, dict):
        raise HTTPException(status_code=422, detail="model_ref.parameters must be an object")
    bound, bind_issues, _clamped = model.bind_parameters(params)
    if bind_issues:
        raise HTTPException(
            status_code=422, detail={"message": "参数绑定失败", "issues": bind_issues}
        )
    checks = run_invariant_checks(model, bound)
    return {
        "id": row.id,
        "model": model_name,
        "passed": all(c.passed for c in checks),
        "checks": [
            {"name": c.name, "passed": c.passed, "detail": c.detail} for c in checks
        ],
    }
