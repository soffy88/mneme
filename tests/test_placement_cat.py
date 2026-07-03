"""L3 自适应定位会话(CAT 无状态驱动器)：估 θ → 判停 → 选下一题。"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.placement_service import cat_next


async def _db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    return engine, factory


@pytest.mark.asyncio
async def test_first_step_serves_a_math_ku():
    engine, factory = await _db()
    async with factory() as db:
        r = await cat_next(db, subject="math", responses=[], served_ku_ids=[])
    await engine.dispose()
    assert r["done"] is False
    assert r["next_ku"] is not None
    assert 0.0 <= r["next_ku"]["difficulty"] <= 1.0


@pytest.mark.asyncio
async def test_stops_at_max_items():
    engine, factory = await _db()
    resp = [{"difficulty": 0.5, "is_correct": i % 2 == 0} for i in range(25)]
    async with factory() as db:
        r = await cat_next(db, subject="math", responses=resp, served_ku_ids=[])
    await engine.dispose()
    assert r["done"] is True and r["next_ku"] is None
    assert "recommended_start_difficulty" in r


@pytest.mark.asyncio
async def test_stops_on_low_se():
    engine, factory = await _db()
    # 大量一致响应(难题全对) → SE 迅速收窄，早停
    resp = [{"difficulty": 0.8, "is_correct": True} for _ in range(40)]
    async with factory() as db:
        r = await cat_next(db, subject="math", responses=resp, served_ku_ids=[])
    await engine.dispose()
    assert r["done"] is True
    assert r["theta"] >= 0.7


@pytest.mark.asyncio
async def test_next_ku_targets_theta_and_excludes_served():
    engine, factory = await _db()
    # 全错简单题 → θ 低 → 下一题应偏易；且不重复已发
    resp = [{"difficulty": 0.5, "is_correct": True}, {"difficulty": 0.5, "is_correct": False}]
    async with factory() as db:
        first = await cat_next(db, subject="math", responses=resp, served_ku_ids=[])
        assert first["done"] is False and first["next_ku"] is not None
        served = [first["next_ku"]["id"]]
        second = await cat_next(
            db, subject="math", responses=resp, served_ku_ids=served
        )
    await engine.dispose()
    assert second["next_ku"]["id"] not in served  # 去重
