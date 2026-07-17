"""合规硬删除（P1-7）：软删（deleted_at）后过宽限期，物理清除该用户全部数据。

审计缺口：此前只有软删（deleted_at 置位），PII 物理永久保留，不符 PIPL 数据最小化 /
COPPA 2025「禁止无限期保留儿童数据」。本模块把"被遗忘权"闭环到物理删除。

永久档案 vs 原始明细的合规拆分：
  · 掌握度模型状态（kc_mastery/mastery_snapshots）——聚合、可长期保留（护城河）。
  · 原始交互明细（interaction_events 等）——含 PII 关联，随用户删除一并清除。
一旦用户注销/监护人撤回同意，两类数据都被本任务物理清除（不因"用于改进算法"而滞留）。
"""

from __future__ import annotations

import os
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# (表, 关联列)：按 FK 依赖，先删子表引用，最后删 users。
# parent_student 两列都要清（学生被删，或家长被删）。
_STUDENT_TABLES: list[tuple[str, str]] = [
    ("interaction_events", "student_id"),
    ("interaction_history", "student_id"),
    ("kc_mastery", "student_id"),
    ("mastery_snapshots", "student_id"),
    ("wrong_questions", "student_id"),
    ("daily_missions", "student_id"),
    ("effortful_gains", "student_id"),
    ("error_tags", "student_id"),
    ("guardian_consents", "student_id"),
    ("highlights", "student_id"),
    ("papers", "student_id"),
    ("parent_alerts", "student_id"),
    ("reading_notes", "student_id"),
    ("socratic_sessions", "student_id"),
    ("speaking_sessions", "student_id"),
    ("streaks", "student_id"),
    ("timed_quizzes", "student_id"),
    ("user_learner_profiles", "student_id"),
    # textbook_files 必须排在 highlights/reading_notes 之后——它俩 file_id 外键
    # 指向 textbook_files，先删父行会违反外键。列名是 owner_student_id 不是 student_id。
    ("textbook_files", "owner_student_id"),
    # Phase1 门控内核 gate schema（独立 schema，无 FK，可任意序删）：三表皆带
    # student_id（未成年 PII 关联），随用户删除一并物理清除（合规红线）。
    ("gate.pending_question", "student_id"),
    ("gate.qualitative_mastery", "student_id"),
    ("gate.evidence", "student_id"),
    # S3 三层 Agent Memory schema（独立 schema，无 FK，可任意序删）：三表皆带
    # student_id（未成年 PII 关联），FC-2：新表同 PR 入清单。
    ("agent.working_memory", "student_id"),
    ("agent.episodic_memory", "student_id"),
    ("agent.semantic_memory", "student_id"),
]


def _grace_days() -> int:
    try:
        return int(os.environ.get("RETENTION_HARD_DELETE_DAYS", "30"))
    except ValueError:
        return 30


async def purge_deleted_users(
    db: AsyncSession, *, grace_days: int | None = None
) -> dict:
    """物理清除软删超过宽限期的用户及其全部数据。返回 {purged_users, ids, tables}。"""
    grace = _grace_days() if grace_days is None else grace_days

    ids = [
        row[0]
        for row in (
            await db.execute(
                text(
                    "SELECT id FROM users "
                    "WHERE deleted_at IS NOT NULL "
                    "AND deleted_at < now() - make_interval(days => :g)"
                ),
                {"g": grace},
            )
        ).all()
    ]
    if not ids:
        return {"purged_users": 0, "ids": [], "tables": {}}

    id_strs = [str(i) for i in ids]
    tables: dict[str, int] = {}

    for table, col in _STUDENT_TABLES:
        res = await db.execute(
            text(f"DELETE FROM {table} WHERE {col} = ANY(:ids)"),  # noqa: S608 表名来自内部白名单
            {"ids": id_strs},
        )
        rc = getattr(res, "rowcount", 0)
        if rc:
            tables[table] = rc

    # parent_student：学生或家长任一方被删都清
    res = await db.execute(
        text(
            "DELETE FROM parent_student "
            "WHERE student_id = ANY(:ids) OR parent_id = ANY(:ids)"
        ),
        {"ids": id_strs},
    )
    rc = getattr(res, "rowcount", 0)
    if rc:
        tables["parent_student"] = rc

    # 最后删用户本体
    res = await db.execute(
        text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": id_strs}
    )
    tables["users"] = getattr(res, "rowcount", 0)

    return {"purged_users": len(ids), "ids": id_strs, "tables": tables}


async def request_delete_and_purge_now(db: AsyncSession, student_id: uuid.UUID) -> dict:
    """立即硬删（宽限期=0）——用于监护人明确要求即时删除的场景。"""
    from sqlalchemy import update

    from services.models import User

    from datetime import datetime, timezone

    await db.execute(
        update(User)
        .where(User.id == student_id)
        .values(deleted_at=datetime.now(timezone.utc))
    )
    return await purge_deleted_users(db, grace_days=0)
