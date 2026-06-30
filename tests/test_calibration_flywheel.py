"""item 5：BKT 先验校准（数据飞轮）。从真实作答校准 p_slip 并写 calibrated_from_n。"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.calibration_service import calibrate_bkt_priors
from services.models import BKTPrior, InteractionEvent, InteractionSource, User, UserRole

KC = f"CAL-KC-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
async def db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    sids = []
    async with factory() as s:
        # 种子先验：低 slip
        s.add(BKTPrior(knowledge_point=KC, question_type="solve",
                       p_init=0.2, p_transit=0.2, p_guess=0.02, p_slip=0.10))
        await s.flush()
        yield s, sids
        await s.execute(delete(InteractionEvent).where(InteractionEvent.knowledge_point == KC))
        await s.execute(delete(BKTPrior).where(BKTPrior.knowledge_point == KC))
        for sid in sids:
            await s.execute(delete(User).where(User.id == sid))
        await s.commit()
    await engine.dispose()


async def _add_events(s, sids, *, students, attempts, warm_error_rate):
    """每个学生做 `attempts` 次；第2次起按 warm_error_rate 出错。"""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(students):
        sid = uuid.uuid4()
        sids.append(sid)
        s.add(User(id=sid, phone=f"1{str(sid.int)[:10]}", role=UserRole.student))
        await s.flush()
        for a in range(attempts):
            # 首次正确（冷样本不计入暖统计）；暖样本按错误率
            correct = True if a == 0 else (a % max(1, round(1 / warm_error_rate)) != 0)
            s.add(InteractionEvent(
                student_id=sid, knowledge_point=KC, source=InteractionSource.quick,
                is_correct=correct, occurred_at=base + timedelta(hours=a),
            ))
    await s.flush()


@pytest.mark.asyncio
async def test_calibration_moves_slip_and_sets_n(db):
    s, sids = db
    # 10 个学生各 5 次（暖样本 40），暖错误率较高 → slip 应被上调
    await _add_events(s, sids, students=10, attempts=5, warm_error_rate=0.5)

    before = (await s.execute(select(BKTPrior).where(BKTPrior.knowledge_point == KC))).scalar_one()
    assert (before.calibrated_from_n or 0) == 0
    slip_before = before.p_slip

    result = await calibrate_bkt_priors(s, min_warm=10)
    await s.commit()

    assert result["calibrated_kcs"] == 1
    after = (await s.execute(select(BKTPrior).where(BKTPrior.knowledge_point == KC))).scalar_one()
    assert after.calibrated_from_n > 0                 # 飞轮真的写回了
    assert after.p_slip > slip_before                  # 高暖错误率 → slip 上调
    assert 0.01 <= after.p_slip <= 0.40                # clamp 生效


@pytest.mark.asyncio
async def test_insufficient_warm_samples_skipped(db):
    s, sids = db
    await _add_events(s, sids, students=1, attempts=3, warm_error_rate=0.5)  # 暖样本仅 2
    result = await calibrate_bkt_priors(s, min_warm=15)
    await s.commit()
    assert result["calibrated_kcs"] == 0
    row = (await s.execute(select(BKTPrior).where(BKTPrior.knowledge_point == KC))).scalar_one()
    assert (row.calibrated_from_n or 0) == 0           # 样本不足不动先验
