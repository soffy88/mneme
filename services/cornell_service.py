"""康奈尔笔记进度云同步（Phase C）。

服务层：鉴权在路由完成；此处只做读/合并写/删。
红线：绝不调用 process_interaction / 不写 kc_mastery。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from services.cornell_merge import CornellMergeError, merge_cornell_state
from services.models import CornellProgress


def _serialize_row(row: CornellProgress) -> dict[str, Any]:
    state = dict(row.state or {})
    # 保证 topicId / version 与行主键一致
    state["topicId"] = row.topic_id
    state["version"] = row.version
    if row.updated_at is not None:
        ts = row.updated_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        state.setdefault("updatedAt", ts.isoformat().replace("+00:00", "Z"))
    return {
        "topic_id": row.topic_id,
        "version": row.version,
        "state": state,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def get_progress(
    db: AsyncSession, student_id: uuid.UUID, topic_id: str
) -> dict[str, Any] | None:
    row = (
        await db.execute(
            select(CornellProgress).where(
                CornellProgress.student_id == student_id,
                CornellProgress.topic_id == topic_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return _serialize_row(row)


async def list_progress(db: AsyncSession, student_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(CornellProgress)
                .where(CornellProgress.student_id == student_id)
                .order_by(CornellProgress.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_serialize_row(r) for r in rows]


async def put_progress(
    db: AsyncSession,
    student_id: uuid.UUID,
    topic_id: str,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """合并写入：云端已有则并集；无则新建。

    incoming 应为进度 State（含 topicId/mastered/…）。
    topicId 必须与路径 topic_id 一致。
    """
    if not isinstance(incoming, dict):
        raise CornellMergeError("state must be an object")

    tid = incoming.get("topicId") or topic_id
    if tid != topic_id:
        raise CornellMergeError(f"topicId mismatch: path={topic_id!r} body={tid!r}")

    # 规范化
    incoming = {
        **incoming,
        "topicId": topic_id,
        "version": int(incoming.get("version") or 1),
        "mastered": incoming.get("mastered") or {},
        "collapsed": incoming.get("collapsed") or {},
        "selfTest": bool(incoming.get("selfTest", False)),
        "showAnswers": bool(incoming.get("showAnswers", False)),
        "updatedAt": incoming.get("updatedAt")
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    row = (
        await db.execute(
            select(CornellProgress).where(
                CornellProgress.student_id == student_id,
                CornellProgress.topic_id == topic_id,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        merged = incoming
    else:
        local = dict(row.state or {})
        local.setdefault("topicId", row.topic_id)
        local.setdefault("version", row.version)
        merged = merge_cornell_state(local, incoming)

    # updatedAt 语义：取 local/incoming 较新一端（merge_cornell_state 已保证），
    # 不用服务器时间覆盖——否则 merge 的 "较新一端生效" 契约失效，
    # 客户端更新的 selfTest/showAnswers 会被旧端吞掉（test_cornell_cloud 实证）。
    # 行级 updated_at（DB 列）仍用服务器时间，仅用于列表排序。
    merged.setdefault("updatedAt", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    now = datetime.now(timezone.utc)
    version = int(merged.get("version") or 1)

    if row is None:
        row = CornellProgress(
            student_id=student_id,
            topic_id=topic_id,
            version=version,
            state=merged,
            updated_at=now,
        )
        db.add(row)
    else:
        row.version = version
        row.state = merged
        row.updated_at = now

    await db.flush()
    return _serialize_row(row)


async def delete_progress(
    db: AsyncSession, student_id: uuid.UUID, topic_id: str
) -> bool:
    """删除云端进度行。返回是否曾存在。"""
    result = await db.execute(
        delete(CornellProgress).where(
            CornellProgress.student_id == student_id,
            CornellProgress.topic_id == topic_id,
        )
    )
    await db.flush()
    return (cast(CursorResult, result).rowcount or 0) > 0
