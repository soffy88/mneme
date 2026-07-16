"""gate_store — mneme app 侧对 `gate.*` schema 的唯一访问层。

架构 A（MCP 工具面并入 mneme app）：gate.* 是 Phase1 门控内核的持久化，只由本模块读写。
gate 表由 Alembic 迁移 `c4d5e6f7a8b9` 建，无 ORM 模型，本层用 schema 限定的原生 SQL。

决策 D2.2（rev.1）净规则：
    gate_type(kc) = qualitative  ⟺  gate.rubric 命中该 kc；否则 quantitative。
即 **rubric 表本身就是 qualitative 注册表**——写一份 rubric = 把该 KC 注册为定性门控，
与 D1 的 fail-safe（无 rubric 不可走 assess）自洽。
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

QUALITATIVE = "qualitative"
QUANTITATIVE = "quantitative"


async def has_rubric(db: AsyncSession, kc_id: str) -> bool:
    """该 KC 在 gate.rubric 是否有行（＝是否注册为定性门控）。"""
    row = (
        await db.execute(
            text("SELECT 1 FROM gate.rubric WHERE kc_id = :kc"), {"kc": kc_id}
        )
    ).first()
    return row is not None


async def resolve_gate_type(db: AsyncSession, kc_id: str) -> str:
    """D2.2 三层解析塌缩为一条净规则：有 rubric → qualitative；否则 quantitative。"""
    return QUALITATIVE if await has_rubric(db, kc_id) else QUANTITATIVE


async def get_rubric(db: AsyncSession, kc_id: str) -> Optional[dict]:
    """返回 {kc_id, dimensions:[{name,criterion,weight}], author}；无则 None。

    fail-safe：返回 None ⟺ 该 KC 不可走 assess 路径（决策 D1）。
    """
    row = (
        (
            await db.execute(
                text(
                    "SELECT kc_id, dimensions, author FROM gate.rubric WHERE kc_id = :kc"
                ),
                {"kc": kc_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return {
        "kc_id": row["kc_id"],
        "dimensions": row["dimensions"],
        "author": row["author"],
    }


async def get_qualitative_mastery_map(
    db: AsyncSession, student_id: uuid.UUID
) -> dict[str, bool]:
    """投影 gate.qualitative_mastery → {kc_id: passed}（供 ProgressView 组装）。"""
    rows = (
        (
            await db.execute(
                text(
                    "SELECT kc_id, passed FROM gate.qualitative_mastery "
                    "WHERE student_id = CAST(:sid AS uuid)"
                ),
                {"sid": str(student_id)},
            )
        )
        .mappings()
        .all()
    )
    return {r["kc_id"]: r["passed"] for r in rows}


# ── 写路径（切片②-1）───────────────────────────────────────────────────────
# 红线：expected（期望答案）只存 gate.pending_question，永不回传 agent。


async def pose_question(
    db: AsyncSession,
    *,
    question_id: str,
    student_id: uuid.UUID,
    kc_id: str,
    prompt: str,
    expected: Optional[str],
    qtype: str,
) -> None:
    """登记一道待答题。expected 落库于此、永不出 mneme 侧；open 题 expected=None。"""
    await db.execute(
        text(
            "INSERT INTO gate.pending_question "
            "(question_id, student_id, kc_id, prompt, expected, qtype) "
            "VALUES (:qid, CAST(:sid AS uuid), :kc, :prompt, :expected, :qtype)"
        ),
        {
            "qid": question_id,
            "sid": str(student_id),
            "kc": kc_id,
            "prompt": prompt,
            "expected": expected,
            "qtype": qtype,
        },
    )


async def get_pending(
    db: AsyncSession, *, student_id: uuid.UUID, question_id: str
) -> Optional[dict]:
    """取该学生名下这道待答题（含 expected，供服务层判分用，不外传）。无则 None。"""
    row = (
        (
            await db.execute(
                text(
                    "SELECT question_id, kc_id, prompt, expected, qtype "
                    "FROM gate.pending_question "
                    "WHERE student_id = CAST(:sid AS uuid) AND question_id = :qid"
                ),
                {"sid": str(student_id), "qid": question_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


async def get_active_pending(
    db: AsyncSession, *, student_id: uuid.UUID
) -> Optional[dict]:
    """取该学生当前待答题（最新一条，含 expected 供服务层用）。无则 None。

    W1 假设一名学生同时至多一道 pending；多于一条时取 posed_at 最新。
    """
    row = (
        (
            await db.execute(
                text(
                    "SELECT question_id, kc_id, prompt, expected, qtype "
                    "FROM gate.pending_question "
                    "WHERE student_id = CAST(:sid AS uuid) "
                    "ORDER BY posed_at DESC LIMIT 1"
                ),
                {"sid": str(student_id)},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


async def clear_pending(
    db: AsyncSession, *, student_id: uuid.UUID, question_id: str
) -> None:
    """判分并落库成功后清除待答题（幂等：不存在则无操作）。"""
    await db.execute(
        text(
            "DELETE FROM gate.pending_question "
            "WHERE student_id = CAST(:sid AS uuid) AND question_id = :qid"
        ),
        {"sid": str(student_id), "qid": question_id},
    )


async def save_evidence(
    db: AsyncSession,
    *,
    evidence_ref: str,
    student_id: uuid.UUID,
    kc_id: str,
    verdict: dict[str, Any],
    model_id: Optional[str],
) -> str:
    """存 llm_verified 裁决证据（防篡改审计），返回 evidence_ref。"""
    await db.execute(
        text(
            "INSERT INTO gate.evidence "
            "(evidence_ref, student_id, kc_id, verdict, model_id) "
            "VALUES (:ref, CAST(:sid AS uuid), :kc, CAST(:verdict AS jsonb), :model)"
        ),
        {
            "ref": evidence_ref,
            "sid": str(student_id),
            "kc": kc_id,
            "verdict": json.dumps(verdict, ensure_ascii=False),
            "model": model_id,
        },
    )
    return evidence_ref


async def upsert_qualitative_mastery(
    db: AsyncSession,
    *,
    student_id: uuid.UUID,
    kc_id: str,
    passed: bool,
    evidence_ref: Optional[str],
) -> None:
    """concept/design 过门状态 upsert（唯一写入者=ReportResult+guard，防篡改）。"""
    await db.execute(
        text(
            "INSERT INTO gate.qualitative_mastery "
            "(student_id, kc_id, passed, evidence_ref, updated_at) "
            "VALUES (CAST(:sid AS uuid), :kc, :passed, :ref, now()) "
            "ON CONFLICT (student_id, kc_id) DO UPDATE SET "
            "passed = EXCLUDED.passed, evidence_ref = EXCLUDED.evidence_ref, "
            "updated_at = now()"
        ),
        {
            "sid": str(student_id),
            "kc": kc_id,
            "passed": passed,
            "ref": evidence_ref,
        },
    )
