"""匿名同年级联赛（教育理念 02·SDT 归属）：返回本人百分位/段位，无他人 PII。"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.main import app
from services.models import KCMastery, User, UserRole


@pytest.fixture(autouse=True)
def _auth(bypass_auth):
    """正向测试绕过鉴权。"""


@pytest.fixture()
async def db():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


async def _mk_student_with_mastery(db, grade: str, n_mastered: int) -> uuid.UUID:
    sid = uuid.uuid4()
    db.add(
        User(id=sid, phone=f"1{str(sid.int)[:10]}", role=UserRole.student, grade=grade)
    )
    await db.flush()
    for i in range(n_mastered):
        db.add(
            KCMastery(
                student_id=sid,
                knowledge_point=f"KC-{sid.hex[:6]}-{i}",
                p_mastery=0.85,
                p_init=0.2,
                p_transit=0.2,
                p_guess=0.15,
                p_slip=0.12,
            )
        )
    await db.flush()
    return sid


@pytest.mark.asyncio
async def test_league_percentile_and_no_pii():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as db:
        # 同年级三人：掌握 6 / 3 / 1
        top = await _mk_student_with_mastery(db, "高一联赛测", 6)
        mid = await _mk_student_with_mastery(db, "高一联赛测", 3)
        low = await _mk_student_with_mastery(db, "高一联赛测", 1)
        await db.commit()
        ids = [top, mid, low]
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                r = await c.get(f"/v1/league/{top}")
            assert r.status_code == 200
            d = r.json()
            assert d["cohort_size"] == 3
            assert d["my_mastered"] == 6
            assert (
                d["percentile"] is not None and d["percentile"] >= 80
            )  # 最高分高百分位
            assert d["tier"] in ("钻石", "黄金", "白银", "青铜")
            # 无 PII：响应里不出现任何他人 student_id
            body = r.text
            for sid in (mid, low):
                assert str(sid) not in body, "联赛响应泄露了他人 id"
        finally:
            for sid in ids:
                await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
                await db.execute(delete(User).where(User.id == sid))
            await db.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_league_insufficient_cohort_no_ranking():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as db:
        solo = await _mk_student_with_mastery(db, "孤独年级XYZ", 2)
        await db.commit()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                r = await c.get(f"/v1/league/{solo}")
            assert r.status_code == 200
            d = r.json()
            assert d["percentile"] is None  # 样本不足不排名
        finally:
            await db.execute(delete(KCMastery).where(KCMastery.student_id == solo))
            await db.execute(delete(User).where(User.id == solo))
            await db.commit()
    await engine.dispose()
