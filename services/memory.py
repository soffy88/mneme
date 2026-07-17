"""memory — services 层对 `agent.*` 三层 Memory schema 的唯一访问层（S3 骨架）。

`agent.*` 表由 Alembic 迁移 e6f7a8b9c0d1 建，无 ORM 模型，本层用 schema 限定的原生 SQL
（对照 gate_store.py 同一风格）。四模式：audit（只读）/dedup（清重复）/merge（沉淀摘要）/
update（人工校正摘要）。详见 MNEME_MASTER_DESIGN.md 附录·Agent 三层 Memory。

不是 omodul：不强制三件套签名、不强制"失败不 raise"——异常直接向上抛，由调用方处理。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COUNT_TABLES = (
    "agent.working_memory",
    "agent.episodic_memory",
    "agent.semantic_memory",
)


async def _duplicate_episodic_groups(
    db: AsyncSession, student_id: uuid.UUID
) -> list[dict]:
    """按 (session_id, kind, content) 分组找完全重复的 episodic 条目（count>1）。

    返回每组 {session_id, kind, ids}（ids 按 created_at 升序，[0] 是最早一条）。
    audit 与 dedup 共用同一判据——单源，不各写一遍。
    """
    rows = (
        (
            await db.execute(
                text(
                    "SELECT session_id, kind, array_agg(id ORDER BY created_at) AS ids "
                    "FROM agent.episodic_memory "
                    "WHERE student_id = CAST(:sid AS uuid) "
                    "GROUP BY session_id, kind, content "
                    "HAVING count(*) > 1"
                ),
                {"sid": str(student_id)},
            )
        )
        .mappings()
        .all()
    )
    return [
        {"session_id": r["session_id"], "kind": r["kind"], "ids": list(r["ids"])}
        for r in rows
    ]


async def audit(db: AsyncSession, student_id: uuid.UUID) -> dict:
    """只读：三层各自行数 + 疑似重复的 episodic 条目组。"""
    counts = {}
    for qualified in _COUNT_TABLES:
        n = (
            await db.execute(
                # 表名来自内部固定元组（非用户输入），S608 不适用
                text(
                    f"SELECT count(*) FROM {qualified} WHERE student_id = CAST(:sid AS uuid)"
                ),  # noqa: S608
                {"sid": str(student_id)},
            )
        ).scalar_one()
        counts[qualified.split(".")[1]] = n

    dup_groups = await _duplicate_episodic_groups(db, student_id)
    return {
        "counts": counts,
        "duplicate_groups": len(dup_groups),
        "duplicate_rows": sum(len(g["ids"]) - 1 for g in dup_groups),
    }


async def dedup(
    db: AsyncSession, student_id: uuid.UUID, *, dry_run: bool = True
) -> dict:
    """删除 episodic 完全重复项（保留最早一条）。dry_run=True 只报告、不写。"""
    dup_groups = await _duplicate_episodic_groups(db, student_id)
    to_delete: list[uuid.UUID] = []
    for g in dup_groups:
        to_delete.extend(g["ids"][1:])  # 保留 [0]（最早），其余标记删除

    if not dry_run and to_delete:
        await db.execute(
            text("DELETE FROM agent.episodic_memory WHERE id = ANY(:ids)"),
            {"ids": [str(i) for i in to_delete]},
        )

    return {
        "dry_run": dry_run,
        "duplicate_groups": len(dup_groups),
        "deleted_ids": [str(i) for i in to_delete] if not dry_run else [],
        "would_delete_ids": [str(i) for i in to_delete] if dry_run else [],
    }


async def merge(
    db: AsyncSession,
    student_id: uuid.UUID,
    *,
    topic: str,
    episodic_ids: list[uuid.UUID],
) -> dict:
    """把指定 episodic 条目并入 semantic_memory[(student_id, topic)]（机械合并，无 LLM）。

    只合并真实属于该学生的 episodic 行（不存在/不属于该学生的 id 静默跳过，返回
    matched_count 供调用方核对）。幂等：已合并过的 episodic_id 再次传入不会重复入 items。
    """
    existing = (
        (
            await db.execute(
                text(
                    "SELECT content, merged_from FROM agent.semantic_memory "
                    "WHERE student_id = CAST(:sid AS uuid) AND topic = :topic"
                ),
                {"sid": str(student_id), "topic": topic},
            )
        )
        .mappings()
        .first()
    )
    existing_items: list[Any] = (
        list(existing["content"].get("items", [])) if existing else []
    )
    existing_merged: list[str] = list(existing["merged_from"] or []) if existing else []

    fresh_ids = [str(i) for i in episodic_ids if str(i) not in existing_merged]
    rows = (
        (
            await db.execute(
                text(
                    "SELECT id, content FROM agent.episodic_memory "
                    "WHERE student_id = CAST(:sid AS uuid) AND id = ANY(:ids)"
                ),
                {"sid": str(student_id), "ids": fresh_ids},
            )
        )
        .mappings()
        .all()
        if fresh_ids
        else []
    )

    new_items = existing_items + [r["content"] for r in rows]
    new_merged = existing_merged + [str(r["id"]) for r in rows]

    await db.execute(
        text(
            "INSERT INTO agent.semantic_memory "
            "(student_id, topic, content, merged_from, updated_at) "
            "VALUES (CAST(:sid AS uuid), :topic, CAST(:content AS jsonb), "
            "CAST(:merged AS jsonb), now()) "
            "ON CONFLICT (student_id, topic) DO UPDATE SET "
            "content = EXCLUDED.content, merged_from = EXCLUDED.merged_from, "
            "updated_at = now()"
        ),
        {
            "sid": str(student_id),
            "topic": topic,
            "content": json.dumps({"items": new_items}, ensure_ascii=False),
            "merged": json.dumps(new_merged),
        },
    )
    return {
        "topic": topic,
        "matched_count": len(rows),
        "skipped_already_merged": len(episodic_ids) - len(fresh_ids),
        "total_items": len(new_items),
    }


async def update(
    db: AsyncSession, student_id: uuid.UUID, *, topic: str, content: dict
) -> dict:
    """直接覆盖 semantic_memory 的 content（人工/上游校正用，不动 merged_from）。"""
    await db.execute(
        text(
            "INSERT INTO agent.semantic_memory (student_id, topic, content, updated_at) "
            "VALUES (CAST(:sid AS uuid), :topic, CAST(:content AS jsonb), now()) "
            "ON CONFLICT (student_id, topic) DO UPDATE SET "
            "content = EXCLUDED.content, updated_at = now()"
        ),
        {
            "sid": str(student_id),
            "topic": topic,
            "content": json.dumps(content, ensure_ascii=False),
        },
    )
    return {"topic": topic, "updated": True}
