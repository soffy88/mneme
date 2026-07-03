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
