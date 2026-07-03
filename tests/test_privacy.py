"""L6 青少年隐私分层 + 进步优先 overview。"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.models import User, UserRole
from services.privacy import parent_sees_process


@pytest.fixture()
async def db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


async def _student(db, *, birth_year: int, shared: bool) -> User:
    sid = uuid.uuid4()
    u = User(
        id=sid,
        phone=f"1{str(sid.int)[:10]}",
        role=UserRole.student,
        birth_date=date(birth_year, 1, 1),
        share_process_with_parent=shared,
    )
    db.add(u)
    await db.flush()
    return u


@pytest.mark.asyncio
async def test_self_always_sees_own_process(db):
    stu = await _student(db, birth_year=2010, shared=False)
    try:
        assert await parent_sees_process(db, stu, stu.id) is True
    finally:
        await db.execute(delete(User).where(User.id == stu.id))
        await db.commit()


@pytest.mark.asyncio
async def test_parent_of_teen_blocked_by_default(db):
    parent = User(
        id=uuid.uuid4(),
        phone=f"1{uuid.uuid4().int % 10**10:010d}",
        role=UserRole.parent,
    )
    db.add(parent)
    await db.flush()
    teen = await _student(db, birth_year=2012, shared=False)  # ~14 岁
    try:
        assert await parent_sees_process(db, parent, teen.id) is False  # 12+ 默认不可见
    finally:
        await db.execute(delete(User).where(User.id.in_([parent.id, teen.id])))
        await db.commit()


@pytest.mark.asyncio
async def test_parent_sees_when_teen_shares(db):
    parent = User(
        id=uuid.uuid4(),
        phone=f"2{uuid.uuid4().int % 10**10:010d}",
        role=UserRole.parent,
    )
    db.add(parent)
    await db.flush()
    teen = await _student(db, birth_year=2012, shared=True)  # 已协商开放
    try:
        assert await parent_sees_process(db, parent, teen.id) is True
    finally:
        await db.execute(delete(User).where(User.id.in_([parent.id, teen.id])))
        await db.commit()


@pytest.mark.asyncio
async def test_parent_of_young_child_sees_process(db):
    parent = User(
        id=uuid.uuid4(),
        phone=f"3{uuid.uuid4().int % 10**10:010d}",
        role=UserRole.parent,
    )
    db.add(parent)
    await db.flush()
    kid = await _student(db, birth_year=2018, shared=False)  # ~8 岁 <12 监护优先
    try:
        assert await parent_sees_process(db, parent, kid.id) is True
    finally:
        await db.execute(delete(User).where(User.id.in_([parent.id, kid.id])))
        await db.commit()
