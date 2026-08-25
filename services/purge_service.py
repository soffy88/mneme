"""合规硬删除（P1-7）：软删（deleted_at）后过宽限期，物理清除该用户全部数据。

审计缺口：此前只有软删（deleted_at 置位），PII 物理永久保留，不符 PIPL 数据最小化 /
COPPA 2025「禁止无限期保留儿童数据」。本模块把"被遗忘权"闭环到物理删除。

永久档案 vs 原始明细的合规拆分：
  · 掌握度模型状态（kc_mastery/mastery_snapshots）——聚合、可长期保留（护城河）。
  · 原始交互明细（interaction_events 等）——含 PII 关联，随用户删除一并清除。
一旦用户注销/监护人撤回同意，两类数据都被本任务物理清除（不因"用于改进算法"而滞留）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import UTC

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# (表, 关联列)：按 FK 依赖排序，先删子表引用，最后删 users。
# FK 依赖（对齐 live DB pg_constraint，2026-08 实测）：
#   lesson_pages.question_id → wrong_questions.id（且 lesson_pages 无 student_id 列，
#     必须按 question_id 反查 wrong_questions 的子集删除，见 _delete_lesson_pages）
#   socratic_sessions.question_id → wrong_questions.id
#   wrong_questions.paper_id → papers.id
#   reading_notes.highlight_id → highlights.id
#   highlights.file_id → textbook_files.id
#   reading_notes.file_id → textbook_files.id
#   textbook_chunks.file_id → textbook_files.id（ON DELETE CASCADE，靠级联，不入清单）
# 因此正确删除顺序（先子后父）：
#   …纯学生子表 → socratic_sessions → wrong_questions → reading_notes →
#   highlights → papers → textbook_files → parent_student/parent_alerts → users
# parent_student / parent_alerts 的 parent_id 也指向 users，须双列清（见 _PARENT_TABLES）。
_STUDENT_TABLES: list[tuple[str, str]] = [
    # 纯学生子表（只指向 users，互相无 FK）
    ("interaction_events", "student_id"),
    ("learning_events", "student_id"),
    ("memory_evidence", "student_id"),
    ("memory_claims", "student_id"),
    ("interaction_history", "student_id"),
    ("kc_mastery", "student_id"),
    ("mastery_snapshots", "student_id"),
    ("daily_missions", "student_id"),
    ("effortful_gains", "student_id"),
    ("error_tags", "student_id"),
    ("guardian_consents", "student_id"),
    ("cornell_progress", "student_id"),
    ("speaking_sessions", "student_id"),
    ("streaks", "student_id"),
    ("timed_quizzes", "student_id"),
    ("user_learner_profiles", "student_id"),
    # socratic_sessions 先于 wrong_questions（其 question_id 指向 wrong_questions.id）
    ("socratic_sessions", "student_id"),
    # wrong_questions 先于 papers（其 paper_id 指向 papers.id）
    ("wrong_questions", "student_id"),
    # reading_notes 先于 highlights / textbook_files
    ("reading_notes", "student_id"),
    # highlights 先于 textbook_files（其 file_id 指向 textbook_files.id）
    ("highlights", "student_id"),
    ("papers", "student_id"),
    # textbook_files：highlight_id 列名是 owner_student_id 不是 student_id。
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
    # W5 Partners schema（同一 agent schema，无 FK，可任意序删）：两表皆带
    # student_id（未成年 PII 关联），FC-2：新表同 PR 入清单。
    ("agent.partner_channel_bindings", "student_id"),
    ("agent.partner_push_log", "student_id"),
    # W5 Part B 多用户 schema（同一 agent schema，无 FK，可任意序删）：两表皆带
    # student_id（未成年 PII 关联，即便是 admin 账号本质仍是 users 表同一行），
    # FC-2：新表同 PR 入清单。
    ("agent.user_grants", "student_id"),
    ("agent.audit_log", "student_id"),
]

# student_id 与 parent_id 双列都指向 users.id 的表：学生被删或家长被删都须清。
_PARENT_TABLES: list[str] = [
    "parent_student",
    "parent_alerts",
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

    # lesson_pages 无 student_id 列，且其 question_id 指向 wrong_questions.id，
    # 必须先于 wrong_questions 按 question_id 反查删除，否则 FK 卡死整个 purge。
    await _delete_lesson_pages(db, id_strs, tables)

    # textbook_files 删行前先收集 storage_path（MinIO 孤儿 blob 清理用，见
    # _delete_textbook_files_blobs）。注意顺序：textbook_files 在清单中位次靠后，
    # 但删行发生在循环里，blob 清理紧随其后即可。
    await _collect_textbook_storage_paths(db, id_strs)

    # memory_claim_evidence has no student_id of its own.  Remove its edges
    # before the student-scoped claim/evidence rows (and before users), even
    # though the FK cascade is a second line of defence.
    if await _table_exists(db, "memory_claim_evidence"):
        res = await db.execute(
            text(
                "DELETE FROM memory_claim_evidence WHERE claim_id IN ("
                "SELECT id FROM memory_claims WHERE student_id = ANY(:ids)"
                ") OR evidence_id IN ("
                "SELECT id FROM memory_evidence WHERE student_id = ANY(:ids)"
                ")"
            ),
            {"ids": id_strs},
        )
        rc = getattr(res, "rowcount", 0)
        if rc:
            tables["memory_claim_evidence"] = rc

    for table, col in _STUDENT_TABLES:
        if not await _table_exists(db, table):
            continue
        res = await db.execute(
            text(f"DELETE FROM {table} WHERE {col} = ANY(:ids)"),
            {"ids": id_strs},
        )
        rc = getattr(res, "rowcount", 0)
        if rc:
            tables[table] = rc

    # parent_student / parent_alerts：student_id 或 parent_id 任一方被删都清
    for table in _PARENT_TABLES:
        res = await db.execute(
            text(
                f"DELETE FROM {table} "
                "WHERE student_id = ANY(:ids) OR parent_id = ANY(:ids)"
            ),
            {"ids": id_strs},
        )
        rc = getattr(res, "rowcount", 0)
        if rc:
            tables[table] = rc

    # 最后删用户本体
    res = await db.execute(
        text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": id_strs}
    )
    tables["users"] = getattr(res, "rowcount", 0)

    # MinIO 孤儿 blob 清理（best-effort，不阻塞已完成的 DB 物理删除）
    await _delete_textbook_files_blobs()

    return {"purged_users": len(ids), "ids": id_strs, "tables": tables}


async def _table_exists(db: AsyncSession, table: str) -> bool:
    """运行时表（interaction_history/error_tags 等由 app 启动时创建）在纯净
    DB 上可能不存在；缺失时跳过，避免 UndefinedTableError 拖死整批 purge。"""
    if "." in table:
        schema, name = table.split(".", 1)
        qualified = f"{schema}.{name}"
    else:
        qualified = table
    row = await db.execute(text("SELECT to_regclass(:t)"), {"t": qualified})
    return row.scalar() is not None


async def _delete_lesson_pages(db: AsyncSession, id_strs: list[str], tables: dict) -> None:
    """lesson_pages 无 student_id 列，靠 question_id → wrong_questions.id 关联，
    须在删 wrong_questions 之前按该学生的错题子集删除。"""
    if not await _table_exists(db, "lesson_pages"):
        return
    res = await db.execute(
        text(
            "DELETE FROM lesson_pages WHERE question_id IN ("
            "  SELECT id FROM wrong_questions WHERE student_id = ANY(:ids)"
            ")"
        ),
        {"ids": id_strs},
    )
    rc = getattr(res, "rowcount", 0)
    if rc:
        tables["lesson_pages"] = rc


async def request_delete_and_purge_now(db: AsyncSession, student_id: uuid.UUID) -> dict:
    """立即硬删（宽限期=0）——用于监护人明确要求即时删除的场景。"""
    from datetime import datetime

    from sqlalchemy import update

    from services.models import User

    await db.execute(
        update(User)
        .where(User.id == student_id)
        .values(deleted_at=datetime.now(UTC))
    )
    return await purge_deleted_users(db, grace_days=0)


# 模块级占位：本任务从 DB 删除用户时，顺带清理其 MinIO blob（教材文件），
# 不留孤儿对象。MinIO 故障不阻断 PII 物理删除（合规优先，blob 由巡检兜底）。
_collected_storage_paths: list[str] = []


async def _collect_textbook_storage_paths(db: AsyncSession, id_strs: list[str]) -> None:
    """删行前收集该学生 textbook_files 的 storage_path，供 blob 清理。"""
    global _collected_storage_paths
    if not await _table_exists(db, "textbook_files"):
        _collected_storage_paths = []
        return
    rows = (
        await db.execute(
            text(
                "SELECT storage_path FROM textbook_files "
                "WHERE owner_student_id = ANY(:ids)"
            ),
            {"ids": id_strs},
        )
    ).all()
    _collected_storage_paths = [r[0] for r in rows if r[0]]


async def _delete_textbook_files_blobs() -> None:
    """把收集到的 storage_path 对应的 MinIO 对象删掉（孤儿 blob 清理）。

    best-effort：MinIO 不可达/对象已不存在都不应拖垮 PII 硬删主流程——
    删不掉的对象留着由 future 巡检任务兜底，但 DB 删除必须完成（合规红线）。
    """
    global _collected_storage_paths
    paths, _collected_storage_paths = _collected_storage_paths, []
    if not paths:
        return
    try:
        from services.storage import delete_file

        for p in paths:
            try:
                await asyncio.to_thread(delete_file, p)
            except Exception:  # noqa: BLE001 — best-effort，单对象失败不阻断其余
                logger.warning("MinIO blob 删除失败（留待巡检兜底）: %s", p)
    except Exception:  # noqa: BLE001 — best-effort，MinIO 整体不可达不阻断 DB 删除
        logger.warning("MinIO 不可达，blob 清理跳过（DB 删除已优先完成）")
