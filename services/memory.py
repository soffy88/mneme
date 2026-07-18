"""memory — services 层对 `agent.*` 三层 Memory schema 的唯一访问层（S3 骨架 + C5 follow-ups）。

`agent.*` 表由 Alembic 迁移 e6f7a8b9c0d1 建，无 ORM 模型，本层用 schema 限定的原生 SQL
（对照 gate_store.py 同一风格）。四模式：audit（只读）/dedup（清重复）/merge（沉淀摘要，
C5 起可选接 LLM 语义合并）/update（人工校正摘要）；另有 `append_episode`（写入新条目，
C5 补——四模式此前只管维护既有条目，没有"新增"入口）/`recall`（呈现层上下文召回）/
`cleanup_expired_working_memory`（TTL 清理）。详见 MNEME_MASTER_DESIGN.md 附录·Agent
三层 Memory。

不是 omodul：不强制三件套签名、不强制"失败不 raise"——异常直接向上抛，由调用方处理。

红线（C5 起有真实调用方，需明说）：memory 是**呈现层上下文**，不进门控判据——本模块
不得 import 任何门控/判分模块（mastery_gate/gate_store/grade/verdict_guard/
cognitive_service），`tests/test_memory_no_gating_coupling.py` 静态断言此边界（对照
C3 persona 同一红线测试）。
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COUNT_TABLES = (
    "agent.working_memory",
    "agent.episodic_memory",
    "agent.semantic_memory",
)


async def append_episode(
    db: AsyncSession,
    student_id: uuid.UUID,
    *,
    kind: str,
    content: dict,
    session_id: Optional[str] = None,
    source_ref: Optional[str] = None,
) -> dict:
    """写入一条 episodic 记录（只增不改，对齐 platform/3O append_episode.py 语义）。

    C5 MCP wiring 用：loop 每轮对话把"发生了什么"记一笔，供后续 merge 沉淀摘要。
    """
    new_id = (
        await db.execute(
            text(
                "INSERT INTO agent.episodic_memory "
                "(student_id, session_id, kind, content, source_ref) "
                "VALUES (CAST(:sid AS uuid), :session_id, :kind, "
                "CAST(:content AS jsonb), :source_ref) RETURNING id"
            ),
            {
                "sid": str(student_id),
                "session_id": session_id,
                "kind": kind,
                "content": json.dumps(content, ensure_ascii=False),
                "source_ref": source_ref,
            },
        )
    ).scalar_one()
    return {"id": str(new_id), "kind": kind}


async def recall(
    db: AsyncSession,
    student_id: uuid.UUID,
    *,
    topic: Optional[str] = None,
    limit: int = 5,
) -> dict:
    """呈现层上下文召回：读 semantic_memory（按 topic 精确取，或最近更新的若干条）。

    只读、不进门控判据——纯供 chat/tutor loop 拼 system prompt 的背景信息用。
    """
    if topic:
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT topic, content FROM agent.semantic_memory "
                        "WHERE student_id = CAST(:sid AS uuid) AND topic = :topic"
                    ),
                    {"sid": str(student_id), "topic": topic},
                )
            )
            .mappings()
            .all()
        )
    else:
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT topic, content FROM agent.semantic_memory "
                        "WHERE student_id = CAST(:sid AS uuid) "
                        "ORDER BY updated_at DESC LIMIT :limit"
                    ),
                    {"sid": str(student_id), "limit": limit},
                )
            )
            .mappings()
            .all()
        )
    return {"memories": [{"topic": r["topic"], "content": r["content"]} for r in rows]}


async def cleanup_expired_working_memory(db: AsyncSession) -> dict:
    """删除已过期的 working_memory 行（expires_at < now()）。TTL 清理任务用。"""
    deleted = (
        (
            await db.execute(
                text(
                    "DELETE FROM agent.working_memory WHERE expires_at < now() "
                    "RETURNING id"
                )
            )
        )
        .scalars()
        .all()
    )
    return {"deleted_count": len(deleted)}


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


_MERGE_SUMMARY_PROMPT = (
    "你在维护一份关于学生学习情况的持续摘要，供对话时的背景参考，**不影响判分/门控**。\n"
    "已有摘要：{existing}\n\n"
    "新增的原始记录：\n{new_texts}\n\n"
    "请给出更新后的摘要——合并新旧信息、去掉重复、保留更准确/更新的说法（对照"
    "「同一意思的两条，保留表述更好的一条」的合并原则），1-3 句话、中文。"
    "只输出摘要文本本身，不要解释、不要加引号。"
)


async def _consolidate_with_llm(
    llm: Callable[[str], Awaitable[str]],
    *,
    existing_summary: Optional[str],
    new_contents: list[Any],
) -> Optional[str]:
    """调注入 LLM 生成/更新语义摘要。失败不阻断合并——只是这轮没更新摘要。"""
    prompt = _MERGE_SUMMARY_PROMPT.format(
        existing=existing_summary or "（无）",
        new_texts="\n".join(
            f"- {json.dumps(c, ensure_ascii=False)}" for c in new_contents
        ),
    )
    try:
        summary = (await llm(prompt)).strip()
        return summary or None
    except Exception:
        return None


async def merge(
    db: AsyncSession,
    student_id: uuid.UUID,
    *,
    topic: str,
    episodic_ids: list[uuid.UUID],
    llm: Optional[Callable[[str], Awaitable[str]]] = None,
) -> dict:
    """把指定 episodic 条目并入 semantic_memory[(student_id, topic)]。

    机械部分（不变）：累积 items + merged_from 溯源，幂等——已合并过的 episodic_id
    再次传入不会重复入 items。

    ``llm``（C5 新增，可选）：注入后额外生成/更新一份语义摘要（``content.summary``），
    对照 DeepTutor `dedup` 的合并策略（同意思的两条保留表述更好的一条），不是简单拼接
    原文。``llm=None`` 时行为与之前完全一致（纯机械累积，无 summary 字段）。LLM 调用
    失败不阻断合并（fail-safe，只是这轮没更新摘要）。

    只合并真实属于该学生的 episodic 行（不存在/不属于该学生的 id 静默跳过，返回
    matched_count 供调用方核对）。
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
    existing_content: dict = existing["content"] if existing else {}
    existing_items: list[Any] = list(existing_content.get("items", []))
    existing_summary: Optional[str] = existing_content.get("summary")
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

    summary = existing_summary
    if llm is not None and rows:
        consolidated = await _consolidate_with_llm(
            llm,
            existing_summary=existing_summary,
            new_contents=[r["content"] for r in rows],
        )
        if consolidated is not None:
            summary = consolidated

    content: dict[str, Any] = {"items": new_items}
    if summary is not None:
        content["summary"] = summary

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
            "content": json.dumps(content, ensure_ascii=False),
            "merged": json.dumps(new_merged),
        },
    )
    return {
        "topic": topic,
        "matched_count": len(rows),
        "skipped_already_merged": len(episodic_ids) - len(fresh_ids),
        "total_items": len(new_items),
        "summary": summary,
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
