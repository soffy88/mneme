"""L3 自适应定位会话(CAT 无状态驱动器)：估 θ → 判停 → 选下一题。"""

from __future__ import annotations

import pytest
import uuid
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.placement_service import cat_next
from services.models import KnowledgeCluster, KnowledgeUnit, Textbook


async def _db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    return engine, factory


@pytest.fixture
async def cat_pool():
    """Provide a minimal math KU pool so CAT tests work on a fresh CI database."""

    engine, factory = await _db()
    suffix = uuid.uuid4().hex[:10]
    textbook_id = f"tb-cat-{suffix}"
    cluster_id = f"cl-cat-{suffix}"
    ku_ids = [f"ku-cat-{suffix}-1", f"ku-cat-{suffix}-2"]
    async with factory() as db:
        db.add(
            Textbook(
                id=textbook_id,
                subject="math",
                grade="G10",
                edition="CI",
                book_name="CAT test textbook",
            )
        )
        await db.flush()
        db.add(
            KnowledgeCluster(
                id=cluster_id,
                textbook_id=textbook_id,
                name="CAT test chapter",
                display_order=1,
            )
        )
        await db.flush()
        db.add_all(
            [
                KnowledgeUnit(
                    id=ku_ids[0],
                    textbook_id=textbook_id,
                    cluster_id=cluster_id,
                    name="CAT easy",
                    difficulty=0.3,
                ),
                KnowledgeUnit(
                    id=ku_ids[1],
                    textbook_id=textbook_id,
                    cluster_id=cluster_id,
                    name="CAT hard",
                    difficulty=0.7,
                ),
            ]
        )
        await db.commit()

    yield

    async with factory() as db:
        from sqlalchemy import delete

        await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.id.in_(ku_ids)))
        await db.execute(
            delete(KnowledgeCluster).where(KnowledgeCluster.id == cluster_id)
        )
        await db.execute(delete(Textbook).where(Textbook.id == textbook_id))
        await db.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_first_step_serves_a_math_ku(cat_pool):
    engine, factory = await _db()
    async with factory() as db:
        r = await cat_next(db, subject="math", responses=[], served_ku_ids=[])
    await engine.dispose()
    assert r["done"] is False
    assert r["next_ku"] is not None
    assert 0.0 <= r["next_ku"]["difficulty"] <= 1.0


@pytest.mark.asyncio
async def test_stops_at_max_items(cat_pool):
    engine, factory = await _db()
    resp = [{"difficulty": 0.5, "is_correct": i % 2 == 0} for i in range(25)]
    async with factory() as db:
        r = await cat_next(db, subject="math", responses=resp, served_ku_ids=[])
    await engine.dispose()
    assert r["done"] is True and r["next_ku"] is None
    assert "recommended_start_difficulty" in r


@pytest.mark.asyncio
async def test_stops_on_low_se(cat_pool):
    engine, factory = await _db()
    # 大量一致响应(难题全对) → SE 迅速收窄，早停
    resp = [{"difficulty": 0.8, "is_correct": True} for _ in range(40)]
    async with factory() as db:
        r = await cat_next(db, subject="math", responses=resp, served_ku_ids=[])
    await engine.dispose()
    assert r["done"] is True
    assert r["theta"] >= 0.7


@pytest.mark.asyncio
async def test_next_ku_targets_theta_and_excludes_served(cat_pool):
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
