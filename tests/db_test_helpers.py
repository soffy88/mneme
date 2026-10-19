"""Database cleanup helpers for tests that write append-only event rows."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import LearningEventRecord


async def cleanup_learning_events(
    db: AsyncSession, student_ids: UUID | Iterable[UUID]
) -> None:
    """Delete only the canonical event rows owned by the test students."""
    ids = [student_ids] if isinstance(student_ids, UUID) else list(student_ids)
    if not ids:
        return
    await db.execute(
        delete(LearningEventRecord).where(LearningEventRecord.student_id.in_(ids))
    )


async def cleanup_test_student(db: AsyncSession, student_id: UUID) -> None:
    """Purge exactly one integration-test student using the app inventory."""
    from services.models import Base, User
    from services.purge_service import _STUDENT_TABLES

    for table_name, column_name in _STUDENT_TABLES:
        table = Base.metadata.tables.get(table_name)
        if table is None or column_name not in table.c:
            continue
        await db.execute(delete(table).where(table.c[column_name] == student_id))
    await db.execute(delete(User).where(User.id == student_id))
    await db.commit()
