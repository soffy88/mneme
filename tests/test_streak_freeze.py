"""连胜护盾（P1-10 留存激励）：缺一天有护盾则续上并消耗；无护盾则清零；里程碑赚护盾。"""

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
from services.mission_service import complete_mission
from services.models import DailyMission, MissionType, Streak, User, UserRole


@pytest.fixture()
async def db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


async def _setup(db, *, last_days_ago, current, freezes):
    sid = uuid.uuid4()
    today = datetime.now(timezone.utc).date()
    db.add(User(id=sid, phone=f"1{str(sid.int)[:10]}", role=UserRole.student))
    await db.flush()  # 先落用户，满足 daily_missions/streaks 外键
    db.add(
        Streak(
            student_id=sid,
            current_streak=current,
            longest_streak=current,
            last_completed_date=today - timedelta(days=last_days_ago),
            freezes_available=freezes,
        )
    )
    mid = uuid.uuid4()
    db.add(
        DailyMission(
            id=mid, student_id=sid, date=today, mission_type=MissionType.review
        )
    )
    await db.flush()
    return sid, mid


async def _cleanup(db, sid):
    await db.execute(delete(DailyMission).where(DailyMission.student_id == sid))
    await db.execute(delete(Streak).where(Streak.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


async def _streak(db, sid) -> Streak:
    return (
        await db.execute(select(Streak).where(Streak.student_id == sid))
    ).scalar_one()


@pytest.mark.asyncio
async def test_freeze_protects_streak_on_one_missed_day(db):
    sid, mid = await _setup(db, last_days_ago=2, current=5, freezes=1)
    try:
        res = await complete_mission(db, mid)
        await db.commit()
        assert res["used_freeze"] is True
        s = await _streak(db, sid)
        assert s.current_streak == 6  # 续上，未清零
        assert s.freezes_available == 0  # 消耗 1 张
    finally:
        await _cleanup(db, sid)


@pytest.mark.asyncio
async def test_no_freeze_resets_streak(db):
    sid, mid = await _setup(db, last_days_ago=2, current=5, freezes=0)
    try:
        res = await complete_mission(db, mid)
        await db.commit()
        assert res["used_freeze"] is False
        s = await _streak(db, sid)
        assert s.current_streak == 1  # 清零重来
    finally:
        await _cleanup(db, sid)


@pytest.mark.asyncio
async def test_earn_freeze_at_seven_day_milestone(db):
    # 连胜 6 天，今天连续第 7 天 → 到里程碑赚 1 张护盾
    sid, mid = await _setup(db, last_days_ago=1, current=6, freezes=2)
    try:
        await complete_mission(db, mid)
        await db.commit()
        s = await _streak(db, sid)
        assert s.current_streak == 7
        assert s.freezes_available == 3  # 2 + 1（未超上限 3）
    finally:
        await _cleanup(db, sid)
