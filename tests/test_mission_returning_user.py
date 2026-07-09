"""
X.7 补测试：get_or_create_mission 的"老用户"主路径（有 WrongQuestion+KCMastery，
跳过冷启动，走 daily_mission_workflow 生成任务）。此前只测了冷启动
（test_today_mission_no_mastery，零 WrongQuestion）和幂等（同一天二次调用），
真正日常场景——老用户每天生成任务——零覆盖。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.mission_service import get_or_create_mission
from services.models import (
    DailyMission,
    KCMastery,
    MissionType,
    User,
    UserRole,
    WrongQuestion,
)


@pytest.fixture(scope="function")
async def db():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(scope="function")
async def returning_student(db: AsyncSession):
    """有历史错题+掌握度数据的老用户——应该跳过冷启动，走正常任务生成路径。"""
    sid = uuid.uuid4()
    db.add(
        User(
            id=sid,
            phone=f"183{str(sid)[:8]}",
            role=UserRole.student,
            name="T-returning",
        )
    )
    await db.flush()

    db.add(
        WrongQuestion(
            id=uuid.uuid4(),
            student_id=sid,
            subject="math",
            question_text="1+1=?",
            correct_answer="2",
        )
    )
    db.add(
        KCMastery(
            id=uuid.uuid4(),
            student_id=sid,
            knowledge_point="kc-returning-1",
            p_mastery=0.6,
            p_init=0.2,
            p_transit=0.2,
            p_guess=0.2,
            p_slip=0.1,
            last_interaction_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
    )
    await db.commit()
    yield sid
    await db.execute(delete(DailyMission).where(DailyMission.student_id == sid))
    await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
    await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.mark.asyncio
async def test_returning_user_skips_cold_start_and_builds_review_mission(
    returning_student, db
):
    sid = returning_student
    now = datetime.now(timezone.utc).replace(hour=10)  # 避开23点后的rest分支

    result = await get_or_create_mission(db, sid, _now=now)

    assert "mission" in result
    mission = result["mission"]
    # 有 KCMastery 数据时应该是 review 类型，不是冷启动的 knowledge_focus
    assert mission["mission_type"] == MissionType.review.value
    assert mission["mission_type"] != "cold_start"

    # 落库确认：真的写了一条 DailyMission
    row = (
        await db.execute(
            DailyMission.__table__.select().where(DailyMission.student_id == sid)
        )
    ).fetchone()
    assert row is not None
    print("  老用户跳过冷启动，走 daily_mission_workflow 生成 review 任务并落库 ✓")


@pytest.mark.asyncio
async def test_returning_user_idempotent_same_day(returning_student, db):
    """同一天二次调用应该返回同一条已生成的任务，不会重复跑
    daily_mission_workflow 再生成一条。"""
    sid = returning_student
    now = datetime.now(timezone.utc).replace(hour=10)

    first = await get_or_create_mission(db, sid, _now=now)
    second = await get_or_create_mission(db, sid, _now=now)

    assert first["mission"]["id"] == second["mission"]["id"]

    rows = (
        await db.execute(
            DailyMission.__table__.select().where(DailyMission.student_id == sid)
        )
    ).fetchall()
    assert len(rows) == 1
    print("  老用户同一天二次调用幂等，不重复生成任务 ✓")
