"""memory_inspect — 学生可检视记忆（Studio /memory-inspect 的数据面）。

把两套既有记忆拼成一个"学生本人能看懂、能删"的视图：
- Agent 三层 Memory（agent.episodic_memory / agent.semantic_memory，经 services.memory 访问）
- v2 Evidence Graph 的 memory_claims（证据本身经既有 /v2/memory/evidence/{claim_id} 取）

遗忘（forget）只删**学生本人**的一条：episodic/semantic 行，或一条 memory_claim
（claim 是派生投影；删 claim 只级联删 claim↔evidence 边，**不删 memory_evidence 证据行**——
证据是不可变事实层，也被掌握度/回放等其它投影引用）。

红线：记忆是呈现层上下文，不进门控判据——本模块不 import 任何门控/判分模块；
删除记忆不触碰 kc_mastery / gate.* / interaction_events。
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services import memory
from services.models import MemoryClaim, MemoryClaimEvidence

ForgetLayer = Literal["episodic", "semantic", "claim"]


async def inspect_view(
    db: AsyncSession, student_id: uuid.UUID, *, limit: int = 100
) -> dict:
    """学生本人视角的记忆全貌（不做家长侧脱敏：仅本人可调）。"""
    layers = await memory.list_for_student(db, student_id, limit=limit)
    claims = (
        (
            await db.execute(
                select(MemoryClaim)
                .where(MemoryClaim.student_id == student_id)
                .order_by(MemoryClaim.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    counts: dict[uuid.UUID, int] = {}
    if claims:
        rows = (
            await db.execute(
                select(
                    MemoryClaimEvidence.claim_id,
                    func.count(MemoryClaimEvidence.evidence_id),
                )
                .where(MemoryClaimEvidence.claim_id.in_([c.id for c in claims]))
                .group_by(MemoryClaimEvidence.claim_id)
            )
        ).all()
        counts = {cid: int(n) for cid, n in rows}
    return {
        "student_id": str(student_id),
        "episodic": layers["episodic"],
        "semantic": layers["semantic"],
        "claims": [
            {
                "id": str(c.id),
                "claim_type": c.claim_type,
                "subject_type": c.subject_type,
                "subject_id": c.subject_id,
                "knowledge_ref": c.knowledge_ref,
                "claim_text": c.claim_text,
                "confidence": c.confidence,
                "evidence_level": c.evidence_level or "contract",
                "evidence_count": counts.get(c.id, 0),
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in claims
        ],
    }


async def forget_item(
    db: AsyncSession, student_id: uuid.UUID, *, layer: ForgetLayer, item_id: uuid.UUID
) -> bool:
    """删除学生本人的一条记忆。返回 False 表示不存在或不属于该学生（调用方回 404）。

    不 commit——事务边界由路由决定。
    """
    if layer in ("episodic", "semantic"):
        return await memory.forget(db, student_id, layer=layer, item_id=item_id)
    if layer == "claim":
        deleted = (
            await db.execute(
                delete(MemoryClaim)
                .where(MemoryClaim.id == item_id, MemoryClaim.student_id == student_id)
                .returning(MemoryClaim.id)
            )
        ).scalar_one_or_none()
        return deleted is not None
    raise ValueError(f"unknown memory layer: {layer!r}")
