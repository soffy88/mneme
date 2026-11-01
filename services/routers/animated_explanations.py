"""SVG 动画讲解规格路由（学生本人，需登录；创建/验证仅 admin）。

照搬 teaching_figures 路由纪律：
- POST /v1/animated-explanations            创建规格（admin；verified 恒 False）
- GET  /v1/animated-explanations            列表（学生仅见 verified；admin 可看全部）
- GET  /v1/animated-explanations/{spec_id}  详情（未 verified 的仅 admin 可见）
- POST /v1/animated-explanations/{spec_id}/verify  服务端重跑门禁，全过才置 verified
- GET  /v1/animated-explanations/{spec_id}/assemble  确定性拼装（学生仅 verified 可见）

verified 只由 verify 端点重跑门禁后设置；创建与其它写路径一律不
接受客户端的 verified 输入。AI 生成动画、音频合成与前端展示不在
本次范围（待接点，见嫁接文档）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from obase.admin_identity import is_admin
from obase.db import get_db
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.animated_explanation import (
    AnimationAssemblyError,
    animation_provenance,
    assemble_animation,
    verify_animation,
)
from services.auth_deps import get_current_user
from services.models import AnimatedExplanationSpec, KnowledgeUnit, User, WrongQuestion

router = APIRouter(prefix="/v1/animated-explanations", tags=["animated-explanations"])


class AnimatedExplanationCreate(BaseModel):
    spec: dict


def _public_dict(row: AnimatedExplanationSpec) -> dict:
    return {
        "id": row.id,
        "question_id": row.question_id,
        "ku_id": row.ku_id,
        "spec": row.spec,
        "verified": row.verified,
        "author_id": str(row.author_id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "provenance": animation_provenance(row.spec),
    }


async def _get_or_404(
    db: AsyncSession, spec_id: str
) -> AnimatedExplanationSpec:
    row = await db.get(AnimatedExplanationSpec, spec_id)
    if row is None:
        raise HTTPException(status_code=404, detail="动画讲解规格不存在")
    return row


async def _known_sets(
    db: AsyncSession, spec: dict
) -> tuple[set[str], set[str]]:
    """按规格引用的 question_id/ku_id 取核验集（fail-closed：查无即空集）。"""
    known_questions: set[str] = set()
    known_kus: set[str] = set()
    question_id = spec.get("question_id")
    if isinstance(question_id, str) and question_id.strip():
        try:
            wq = await db.get(WrongQuestion, uuid.UUID(question_id))
        except ValueError:
            wq = None
        if wq is not None:
            known_questions.add(str(wq.id))
    ku_id = spec.get("ku_id")
    if isinstance(ku_id, str) and ku_id.strip():
        ku = await db.get(KnowledgeUnit, ku_id)
        if ku is not None:
            known_kus.add(ku.id)
    return known_questions, known_kus


@router.post("")
async def create_animated_explanation(
    payload: AnimatedExplanationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="仅 admin 可创建动画讲解规格")
    spec = payload.spec
    spec_id = spec.get("id") if isinstance(spec, dict) else None
    if isinstance(spec_id, str):
        if await db.get(AnimatedExplanationSpec, spec_id) is not None:
            raise HTTPException(status_code=409, detail=f"规格 id {spec_id!r} 已存在")
    known_questions, known_kus = await _known_sets(db, spec)
    result = verify_animation(
        spec, known_question_ids=known_questions, known_ku_ids=known_kus
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
    row = AnimatedExplanationSpec(
        id=spec_id,
        question_id=spec.get("question_id"),
        ku_id=spec.get("ku_id"),
        spec=spec,
        verified=False,
        author_id=current_user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _public_dict(row)


@router.get("")
async def list_animated_explanations(
    ku_id: Optional[str] = Query(default=None),
    question_id: Optional[str] = Query(default=None),
    include_unverified: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    admin = is_admin(current_user)
    stmt = select(AnimatedExplanationSpec).order_by(AnimatedExplanationSpec.id)
    if ku_id:
        stmt = stmt.where(AnimatedExplanationSpec.ku_id == ku_id)
    if question_id:
        stmt = stmt.where(AnimatedExplanationSpec.question_id == question_id)
    if not (admin and include_unverified):
        stmt = stmt.where(AnimatedExplanationSpec.verified.is_(True))
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_public_dict(r) for r in rows], "total": len(rows)}


@router.get("/{spec_id}")
async def get_animated_explanation(
    spec_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _get_or_404(db, spec_id)
    if not row.verified and not is_admin(current_user):
        raise HTTPException(status_code=404, detail="动画讲解规格不存在")
    return _public_dict(row)


@router.post("/{spec_id}/verify")
async def verify_animated_explanation(
    spec_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not is_admin(current_user):
        raise HTTPException(status_code=403, detail="仅 admin 可验证动画讲解规格")
    row = await _get_or_404(db, spec_id)
    known_questions, known_kus = await _known_sets(db, row.spec)
    result = verify_animation(
        row.spec, known_question_ids=known_questions, known_ku_ids=known_kus
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
    return _public_dict(row)


@router.get("/{spec_id}/assemble")
async def assemble_animated_explanation(
    spec_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _get_or_404(db, spec_id)
    if not row.verified and not is_admin(current_user):
        raise HTTPException(status_code=404, detail="动画讲解规格不存在")
    try:
        animation = assemble_animation(row.spec)
    except AnimationAssemblyError as exc:
        raise HTTPException(
            status_code=422, detail=f"规格结构损坏，无法拼装：{exc}"
        )
    return {"id": row.id, "verified": row.verified, "animation": animation}
