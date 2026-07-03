"""开放学习者模型(教育理念 03·OLM)：透明返回 P(L)/R/effective/错因画像/下次复习。"""

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


KC = "RENJIAO-G10-MATH-A-ku-集合的概念"


async def _mk(db, *, with_mastery: bool):
    sid = uuid.uuid4()
    db.add(
        User(id=sid, phone=f"1{str(sid.int)[:10]}", role=UserRole.student, grade="高一")
    )
    await db.flush()
    if with_mastery:
        from oprim.fsrs_engine import fsrs_new_card

        db.add(
            KCMastery(
                student_id=sid,
                knowledge_point=KC,
                p_mastery=0.55,
                p_init=0.2,
                p_transit=0.2,
                p_guess=0.15,
                p_slip=0.12,
                p_recognition=0.5,
                p_recognition_init=0.3,
                n_attempts=4,
                fsrs_card_json=fsrs_new_card(),
            )
        )
    await db.flush()
    return sid


@pytest.mark.asyncio
async def test_learner_model_transparent_fields():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as db:
        sid = await _mk(db, with_mastery=True)
        await db.commit()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                r = await c.get(f"/v1/learner-model/{sid}/{KC}")
            assert r.status_code == 200
            d = r.json()
            assert d["started"] is True
            assert d["p_mastery"] == 0.55
            assert d["retrievability"] is not None and 0.0 <= d["retrievability"] <= 1.0
            assert d["effective_mastery"] <= d["p_mastery"]  # ×R 不会超过 P(L)
            ep = d["error_profile"]
            assert abs(ep["careless"] + ep["dontknow"] - 1.0) < 1e-6  # 错因画像归一
            assert d["attempts"] == 4
        finally:
            await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
            await db.execute(delete(User).where(User.id == sid))
            await db.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_learner_model_not_started():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as db:
        sid = await _mk(db, with_mastery=False)
        await db.commit()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                r = await c.get(f"/v1/learner-model/{sid}/{KC}")
            assert r.status_code == 200
            assert r.json()["started"] is False
        finally:
            await db.execute(delete(User).where(User.id == sid))
            await db.commit()
    await engine.dispose()
