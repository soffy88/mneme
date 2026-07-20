"""obase.audit_log — W5 Part B：用户操作审计（append-only）。

对照 DeepTutor multi_user `audit.py` 同一设计：管理员对自己账号的操作不记
（减少审计噪音——真正需要留痕的是"谁访问了谁的数据/谁改了谁的授权"，不是
admin 日常自查）；写审计失败绝不能拖垮正常请求，异常一律吞掉。
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from obase.admin_identity import is_admin

logger = logging.getLogger(__name__)


async def log_usage(
    db: AsyncSession,
    *,
    actor: Any,
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    """记一条使用审计。actor 是 admin 时不记（同 DeepTutor 设计：减少噪音）。"""
    if is_admin(actor):
        return
    await _write(
        db,
        student_id=actor.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        extra=extra,
    )


async def log_admin_action(
    db: AsyncSession,
    *,
    admin_user: Any,
    action: str,
    target_student_id: Optional[UUID] = None,
    extra: Optional[dict] = None,
) -> None:
    """记一条管理动作——admin 自己的操作也要记（这条不受 log_usage 的豁免规则约束）。"""
    await _write(
        db,
        student_id=admin_user.id,
        action=action,
        resource_type="admin_action",
        resource_id=str(target_student_id) if target_student_id else None,
        extra=extra,
    )


async def _write(
    db: AsyncSession,
    *,
    student_id: UUID,
    action: str,
    resource_type: Optional[str],
    resource_id: Optional[str],
    extra: Optional[dict],
) -> None:
    import json

    try:
        await db.execute(
            text(
                "INSERT INTO agent.audit_log "
                "(student_id, action, resource_type, resource_id, extra) "
                "VALUES (:sid, :action, :rtype, :rid, :extra)"
            ),
            {
                "sid": student_id,
                "action": action,
                "rtype": resource_type,
                "rid": resource_id,
                "extra": json.dumps(extra) if extra is not None else None,
            },
        )
    except Exception as e:  # noqa: BLE001 — 审计失败绝不能拖垮正常请求
        logger.error(f"[audit_log] write failed action={action}: {e}")


async def get_audit_log(
    db: AsyncSession, student_id: UUID, *, limit: int = 100
) -> list[dict]:
    rows = (
        await db.execute(
            text(
                "SELECT action, resource_type, resource_id, extra, created_at "
                "FROM agent.audit_log WHERE student_id = :sid "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"sid": student_id, "limit": limit},
        )
    ).all()
    return [
        {
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "extra": extra,
            "created_at": created_at.isoformat() if created_at else None,
        }
        for action, resource_type, resource_id, extra, created_at in rows
    ]
