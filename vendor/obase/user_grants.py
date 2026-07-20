"""obase.user_grants — W5 Part B：admin-curated 工具/模型授权，deny-by-default。

每学生一行 `agent.user_grants`；`enabled_tools`/`allowed_models` 为 NULL 视为
拒绝一切（不是"默认放行"）——非 admin 用户必须被显式授权才能使用某个工具/
模型（对照 DeepTutor multi_user `mcp_tools: None = DENY ALL` 同一语义）。admin
账号（obase.admin_identity.is_admin）不受本模块限制，任何工具/模型均放行。

只有 admin 能设置他人的授权（set_grant 强制校验）；任何学生都能查看自己的
授权（get_grant 本身不做权限检查，调用方在 MCP 层套
_ensure_student_self/_ensure_student_access）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from obase.admin_identity import is_admin


class GrantNotAuthorizedError(Exception):
    """非 admin 尝试设置他人授权。"""


def _to_jsonb_param(value: Optional[list[str]]) -> Optional[str]:
    return json.dumps(value) if value is not None else None


async def get_grant(db: AsyncSession, student_id: UUID) -> dict[str, Any]:
    row = (
        await db.execute(
            text(
                "SELECT enabled_tools, allowed_models, updated_at, updated_by "
                "FROM agent.user_grants WHERE student_id = :sid"
            ),
            {"sid": student_id},
        )
    ).first()

    if row is None:
        return {
            "student_id": str(student_id),
            "enabled_tools": None,
            "allowed_models": None,
            "updated_at": None,
            "updated_by": None,
        }

    enabled_tools, allowed_models, updated_at, updated_by = row
    return {
        "student_id": str(student_id),
        "enabled_tools": enabled_tools,
        "allowed_models": allowed_models,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "updated_by": str(updated_by) if updated_by else None,
    }


async def set_grant(
    db: AsyncSession,
    *,
    admin_user: Any,
    student_id: UUID,
    enabled_tools: Optional[list[str]] = None,
    allowed_models: Optional[list[str]] = None,
) -> dict[str, Any]:
    """写别人的授权是管理动作，不是自助操作——只有 admin 能调用。"""
    if not is_admin(admin_user):
        raise GrantNotAuthorizedError("只有 admin 能设置用户授权")

    await db.execute(
        text(
            "INSERT INTO agent.user_grants "
            "(student_id, enabled_tools, allowed_models, updated_at, updated_by) "
            "VALUES (:sid, :tools, :models, :now, :admin_id) "
            "ON CONFLICT (student_id) DO UPDATE SET "
            "enabled_tools = :tools, allowed_models = :models, "
            "updated_at = :now, updated_by = :admin_id"
        ),
        {
            "sid": student_id,
            "tools": _to_jsonb_param(enabled_tools),
            "models": _to_jsonb_param(allowed_models),
            "now": datetime.now(timezone.utc),
            "admin_id": admin_user.id,
        },
    )
    return await get_grant(db, student_id)


async def is_tool_authorized(
    db: AsyncSession, student_id: UUID, tool_name: str, *, actor: Any = None
) -> bool:
    """actor 若是 admin，直接放行——管理员不受工具白名单限制。"""
    if actor is not None and is_admin(actor):
        return True

    grant = await get_grant(db, student_id)
    enabled = grant["enabled_tools"]
    if enabled is None:
        return False
    return tool_name in enabled


async def is_model_authorized(
    db: AsyncSession, student_id: UUID, model_name: str, *, actor: Any = None
) -> bool:
    if actor is not None and is_admin(actor):
        return True

    grant = await get_grant(db, student_id)
    allowed = grant["allowed_models"]
    if allowed is None:
        return False
    return model_name in allowed
