"""考期感知调度（教育理念 06）：临考(≤14天)停推新知、算距考天数。"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.daily_plan_service import build_daily_plan
from services.models import DailyMission, KCMastery, User, UserRole


@pytest.fixture()
async def db_student():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as db:
        sid = uuid.uuid4()
        db.add(
            User(
                id=sid,
                phone=f"1{str(sid.int)[:10]}",
                role=UserRole.student,
                grade="高三",
            )
        )
        await db.commit()
        yield db, sid
        await db.execute(delete(DailyMission).where(DailyMission.student_id == sid))
        await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
        await db.execute(delete(User).where(User.id == sid))
        await db.commit()
    await engine.dispose()


async def _set_exam(db, sid, d):
    await db.execute(update(User).where(User.id == sid).values(exam_date=d))
    await db.commit()


@pytest.mark.asyncio
async def test_near_exam_suppresses_new_learn(db_student):
    db, sid = db_student
    now = datetime.now(timezone.utc)
    await _set_exam(db, sid, now.date() + timedelta(days=7))  # 7 天后考
    plan = await build_daily_plan(db, sid, now=now)
    assert plan["exam_countdown_days"] == 7
    assert plan["near_exam"] is True
    # 临考不学新：无 new_learn 任务
    assert all(t.get("type") != "new_learn" for t in plan["tasks"])


@pytest.mark.asyncio
async def test_far_exam_allows_new_learn(db_student):
    db, sid = db_student
    now = datetime.now(timezone.utc)
    await _set_exam(db, sid, now.date() + timedelta(days=90))  # 90 天后
    plan = await build_daily_plan(db, sid, now=now)
    assert plan["exam_countdown_days"] == 90
    assert plan["near_exam"] is False  # 远考不进临考窗口


@pytest.mark.asyncio
async def test_no_exam_date_countdown_none(db_student):
    db, sid = db_student
    now = datetime.now(timezone.utc)
    plan = await build_daily_plan(db, sid, now=now)
    assert plan["exam_countdown_days"] is None
    assert plan["near_exam"] is False
