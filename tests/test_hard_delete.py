"""合规硬删除（P1-7）：软删超宽限期 → 物理清除用户及全部 PII；宽限期内保留。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.models import User, UserRole, WrongQuestion
from services.purge_service import purge_deleted_users


@pytest.fixture()
async def db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


async def _mk_user(db, *, deleted_days_ago: int | None) -> uuid.UUID:
    sid = uuid.uuid4()
    deleted_at = (
        None
        if deleted_days_ago is None
        else datetime.now(timezone.utc) - timedelta(days=deleted_days_ago)
    )
    db.add(
        User(
            id=sid,
            phone=f"1{str(sid.int)[:10]}",
            role=UserRole.student,
            deleted_at=deleted_at,
        )
    )
    db.add(
        WrongQuestion(
            id=uuid.uuid4(),
            student_id=sid,
            question_text="q",
            correct_answer="a",
            subject="math",
            knowledge_points={"KC": "x"},
        )
    )
    await db.flush()
    return sid


async def _cleanup(db, sid):
    await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.mark.asyncio
async def test_purge_removes_user_past_grace(db):
    sid = await _mk_user(db, deleted_days_ago=40)
    try:
        result = await purge_deleted_users(db, grace_days=30)
        await db.commit()
        assert sid.__str__() in result["ids"]
        # 用户本体与其错题都被物理清除
        assert (
            await db.execute(select(User).where(User.id == sid))
        ).scalar_one_or_none() is None
        wq = (
            (
                await db.execute(
                    select(WrongQuestion).where(WrongQuestion.student_id == sid)
                )
            )
            .scalars()
            .all()
        )
        assert wq == []
    finally:
        await _cleanup(db, sid)


@pytest.mark.asyncio
async def test_purge_keeps_user_within_grace(db):
    sid = await _mk_user(db, deleted_days_ago=5)
    try:
        result = await purge_deleted_users(db, grace_days=30)
        await db.commit()
        assert str(sid) not in result["ids"]
        assert (
            await db.execute(select(User).where(User.id == sid))
        ).scalar_one_or_none() is not None
    finally:
        await _cleanup(db, sid)


@pytest.mark.asyncio
async def test_purge_ignores_active_user(db):
    """未软删的活跃用户绝不被清。"""
    sid = await _mk_user(db, deleted_days_ago=None)
    try:
        result = await purge_deleted_users(db, grace_days=0)
        assert str(sid) not in result["ids"]
        assert (
            await db.execute(select(User).where(User.id == sid))
        ).scalar_one_or_none() is not None
    finally:
        await _cleanup(db, sid)


@pytest.mark.asyncio
async def test_purge_removes_timed_quiz_and_textbook_file(db):
    """回归：做过限时小测/传过教材的用户也必须能被清（此前 purge 漏了
    timed_quizzes/textbook_files，因外键 NO ACTION 会导致整个删除事务回滚，
    这类未成年 PII 永远删不掉——上线体检发现的删除阻断）。"""
    from services.models import TextbookFile, TimedQuiz

    sid = await _mk_user(db, deleted_days_ago=40)
    tf_id = f"tf-{uuid.uuid4().hex[:8]}"
    db.add(TimedQuiz(id=uuid.uuid4(), student_id=sid, items=[]))
    db.add(
        TextbookFile(
            id=tf_id,
            owner_student_id=sid,
            filename="x.pdf",
            file_type="pdf",
            storage_path="papers/x.pdf",
        )
    )
    await db.flush()
    try:
        result = await purge_deleted_users(db, grace_days=30)
        await db.commit()
        assert str(sid) in result["ids"]
        # 用户本体 + 限时小测 + 教材文件全部物理清除，删除事务未因外键回滚
        assert (
            await db.execute(select(User).where(User.id == sid))
        ).scalar_one_or_none() is None
        assert (
            (await db.execute(select(TimedQuiz).where(TimedQuiz.student_id == sid)))
            .scalars()
            .all()
        ) == []
        assert (
            (
                await db.execute(
                    select(TextbookFile).where(TextbookFile.owner_student_id == sid)
                )
            )
            .scalars()
            .all()
        ) == []
    finally:
        await db.execute(delete(TimedQuiz).where(TimedQuiz.student_id == sid))
        await db.execute(
            delete(TextbookFile).where(TextbookFile.owner_student_id == sid)
        )
        await _cleanup(db, sid)


@pytest.mark.asyncio
async def test_every_student_table_is_in_purge_list(db):
    """守卫测试：任何有 student_id/owner_student_id 列的表，都必须在 purge 清单里。
    这是防止"新增带未成年PII的表却忘了加进删除清单"的 schema 漂移守卫——上一次
    正是因为缺这个守卫，timed_quizzes/textbook_files 漏了没人发现。直接查活库
    information_schema，不靠人肉维护对照表。"""
    from sqlalchemy import text as sql_text

    from services.purge_service import _STUDENT_TABLES

    rows = (
        await db.execute(
            sql_text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema='public'
                  AND column_name IN ('student_id','owner_student_id')
                  AND table_name <> 'users'
                """
            )
        )
    ).all()
    # parent_student 的 student_id 由 purge 里单独处理（parent/student 双向），豁免
    db_tables = {(t, c) for t, c in rows if t != "parent_student"}
    covered = {(t, c) for t, c in _STUDENT_TABLES}
    missing = db_tables - covered
    assert not missing, (
        f"以下带未成年PII的表不在 purge 清单，删除后数据会残留（合规红线）：{sorted(missing)}"
    )
