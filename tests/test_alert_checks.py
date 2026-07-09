"""
X.7 补测试：run_alert_checks 的5个预警阈值判定分支 + 落库去重。此前只测了
_support_for/_ALERT_SUPPORT（话术），5个真正的阈值检测+落库路径零覆盖——
家长告警是儿童福祉相关功能，阈值/去重出bug会导致家长静默收不到告警。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.alert_service import run_alert_checks
from services.models import (
    AlertType,
    DailyMission,
    InteractionEvent,
    InteractionSource,
    KCMastery,
    ParentAlert,
    SocraticSession,
    User,
    UserRole,
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
async def students(db: AsyncSession):
    sid = uuid.uuid4()
    pid = uuid.uuid4()
    db.add(
        User(id=sid, phone=f"181{str(sid)[:8]}", role=UserRole.student, name="T-alert")
    )
    db.add(
        User(id=pid, phone=f"182{str(pid)[:8]}", role=UserRole.parent, name="P-alert")
    )
    await db.commit()
    yield sid, pid
    await db.execute(delete(ParentAlert).where(ParentAlert.student_id == sid))
    await db.execute(delete(SocraticSession).where(SocraticSession.student_id == sid))
    await db.execute(delete(DailyMission).where(DailyMission.student_id == sid))
    await db.execute(delete(InteractionEvent).where(InteractionEvent.student_id == sid))
    await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
    await db.execute(delete(User).where(User.id.in_([sid, pid])))
    await db.commit()


def _mastery_kwargs(**overrides):
    base = dict(p_init=0.2, p_transit=0.2, p_guess=0.2, p_slip=0.1)
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_all_five_thresholds_fire_and_persist(students, db):
    sid, pid = students
    now = datetime.now(timezone.utc)

    # 1. emotion：3天内≥5次苏格拉底会话
    for _ in range(5):
        db.add(SocraticSession(id=uuid.uuid4(), student_id=sid, created_at=now))

    # 2. task_missing：近5天里≥3天未完成
    for i in range(5):
        db.add(
            DailyMission(
                id=uuid.uuid4(),
                student_id=sid,
                date=(now - timedelta(days=i)).date(),
                completed=(i < 1),  # 只有最近1天完成，其余4天未完成 ≥3
            )
        )

    # 3. time_drop：本周互动数 < 上周一半
    for _ in range(2):
        db.add(
            InteractionEvent(
                id=uuid.uuid4(),
                student_id=sid,
                knowledge_point="kc-x",
                source=InteractionSource.quick,
                is_correct=True,
                occurred_at=now - timedelta(days=1),
            )
        )
    for _ in range(10):
        db.add(
            InteractionEvent(
                id=uuid.uuid4(),
                student_id=sid,
                knowledge_point="kc-x",
                source=InteractionSource.quick,
                is_correct=True,
                occurred_at=now - timedelta(days=10),
            )
        )

    # 4. late_night：近3天≥2次23点后作答
    late_time = (now - timedelta(days=1)).replace(hour=23, minute=30)
    for _ in range(2):
        db.add(
            InteractionEvent(
                id=uuid.uuid4(),
                student_id=sid,
                knowledge_point="kc-late",
                source=InteractionSource.quick,
                is_correct=True,
                occurred_at=late_time,
            )
        )

    # 5. score_drop：≥3个知识点掌握度≤0.3
    for i in range(3):
        db.add(
            KCMastery(
                id=uuid.uuid4(),
                student_id=sid,
                knowledge_point=f"kc-weak-{i}",
                p_mastery=0.2,
                **_mastery_kwargs(),
            )
        )

    await db.commit()

    result = await run_alert_checks(db, sid, pid)
    types = {a["type"] for a in result}
    assert types == {
        "emotion",
        "task_missing",
        "time_drop",
        "late_night",
        "score_drop",
    }

    # 落库确认：parent_alerts 里真的写了这5条
    persisted = (
        await db.execute(
            ParentAlert.__table__.select().where(ParentAlert.student_id == sid)
        )
    ).fetchall()
    assert len(persisted) == 5
    print("  5类预警阈值全部正确判定+落库 ✓")


@pytest.mark.asyncio
async def test_same_day_rerun_does_not_duplicate(students, db):
    """同一天内重复跑 run_alert_checks（比如定时任务重试），同类型预警不应该
    重复落库——按 (parent,student,type,当日) 去重。"""
    sid, pid = students

    for i in range(3):
        db.add(
            KCMastery(
                id=uuid.uuid4(),
                student_id=sid,
                knowledge_point=f"kc-weak-{i}",
                p_mastery=0.1,
                **_mastery_kwargs(),
            )
        )
    await db.commit()

    first = await run_alert_checks(db, sid, pid)
    assert len(first) == 1
    assert first[0]["type"] == AlertType.score_drop.value

    second = await run_alert_checks(db, sid, pid)
    assert second == []  # 同一天已存在同类型预警，去重后不再返回/不再落库

    persisted = (
        await db.execute(
            ParentAlert.__table__.select().where(ParentAlert.student_id == sid)
        )
    ).fetchall()
    assert len(persisted) == 1
    print("  同日重复跑不重复落库（按parent+student+type+当日去重）✓")


@pytest.mark.asyncio
async def test_no_alerts_when_thresholds_not_met(students, db):
    """基线：没有任何异常数据时，不应该产生任何预警（防止阈值判定误报）。"""
    sid, pid = students
    result = await run_alert_checks(db, sid, pid)
    assert result == []
    print("  无异常数据时不误报 ✓")
