"""管理员邀请码管理（邀请制学生注册）。

管理员用 ``ADMIN_USER_IDS`` 白名单判定；生成/吊销都需要 admin token。
邀请码本身不经过邮件/短信下发——由管理员线下交付，避免上线依赖 SMTP。
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from obase.admin_identity import is_admin
from obase.db import get_db
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.auth_deps import get_current_user
from services.models import RegistrationInvite, User

router = APIRouter(tags=["invitations"])

# 去掉易混淆字符（0/O、1/I/L），并保证大小写不敏感的码空间足够大。
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class CreateInvitesReq(BaseModel):
    count: int = Field(default=1, ge=1, le=20)
    expires_in_days: int = Field(default=14, ge=1, le=365)
    note: str | None = Field(default=None, max_length=120)


def _new_code() -> str:
    groups = ("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(2))
    return "SXJ-" + "-".join(groups)


def _require_admin(user: User) -> None:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="仅 admin 可管理邀请码")


@router.post("/v1/admin/invitations", status_code=201)
async def create_invitations(
    payload: CreateInvitesReq,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """生成一批单次邀请码（明文只在创建响应中出现一次）。"""
    _require_admin(current_user)
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=payload.expires_in_days)
    created: list[RegistrationInvite] = []
    # 极小概率碰撞：生成后用唯一索引兜底，碰撞则重试。
    for _ in range(payload.count):
        for _attempt in range(5):
            code = _new_code()
            exists = (
                await db.execute(
                    select(RegistrationInvite.id).where(RegistrationInvite.code == code)
                )
            ).scalar_one_or_none()
            if exists is None:
                break
        else:
            raise HTTPException(status_code=503, detail="邀请码生成失败，请重试")
        row = RegistrationInvite(
            code=code,
            note=payload.note,
            created_by=current_user.id,
            expires_at=expires_at,
        )
        db.add(row)
        created.append(row)
    await db.flush()
    for row in created:
        await db.refresh(row)
    issued = [
        {
            "id": str(row.id),
            "code": row.code,
            "note": row.note,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in created
    ]
    await db.commit()
    return {"invitations": issued, "expires_at": expires_at.isoformat()}


@router.get("/v1/admin/invitations")
async def list_invitations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """最近 100 个邀请码状态（不含任何学生 PII）。"""
    _require_admin(current_user)
    rows = (
        await db.execute(
            select(RegistrationInvite)
            .order_by(RegistrationInvite.created_at.desc())
            .limit(100)
        )
    ).scalars().all()
    now = datetime.now(UTC)
    result = []
    for row in rows:
        if row.revoked_at is not None:
            status = "revoked"
        elif row.used_at is not None:
            status = "used"
        elif row.expires_at is not None and row.expires_at <= now:
            status = "expired"
        else:
            status = "available"
        result.append(
            {
                "id": str(row.id),
                "code": row.code,
                "note": row.note,
                "status": status,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "used_at": row.used_at.isoformat() if row.used_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return {"invitations": result}


@router.post("/v1/admin/invitations/{invitation_id}/revoke")
async def revoke_invitation(
    invitation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """吊销一个尚未使用的邀请码（已使用的不可回收）。"""
    _require_admin(current_user)
    try:
        invite_uuid = uuid.UUID(invitation_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="邀请码 ID 格式不正确") from None
    row = (
        await db.execute(
            select(RegistrationInvite)
            .where(RegistrationInvite.id == invite_uuid)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="邀请码不存在")
    if row.used_at is not None:
        raise HTTPException(status_code=409, detail="邀请码已被使用，无法吊销")
    invitation_id_str = str(row.id)
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        await db.commit()
    return {"ok": True, "id": invitation_id_str, "status": "revoked"}
