"""P0: 同一 (student, kc) 并发 process_interaction 不得丢更新。"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from obase.prior_provider import PriorProvider
from services.cognitive_service import process_interaction
from services.models import InteractionEvent, KCMastery, MasterySnapshot, User, UserRole


@pytest.fixture
async def student_factory():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    student_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=student_id,
                phone=f"151{str(uuid.uuid4())[:8]}",
                role=UserRole.student,
            )
        )
        await session.commit()
        await PriorProvider.warm_up(session)

    yield factory, student_id

    async with factory() as session:
        await session.execute(
            delete(MasterySnapshot).where(MasterySnapshot.student_id == student_id)
        )
        await session.execute(
            delete(InteractionEvent).where(InteractionEvent.student_id == student_id)
        )
        await session.execute(
            delete(KCMastery).where(KCMastery.student_id == student_id)
        )
        await session.execute(delete(User).where(User.id == student_id))
        await session.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_process_interaction_preserves_both_updates(student_factory):
    """两会话同时答对同一 KC：n_attempts 必须为 2，事件条数必须为 2。"""
    factory, student_id = student_factory
    kc_id = f"GDMATH-CONC-{uuid.uuid4().hex[:8]}"

    async def one_correct() -> dict:
        async with factory() as session:
            result = await process_interaction(
                session, student_id, kc_id, is_correct=True
            )
            await session.commit()
            return result

    r1, r2 = await asyncio.gather(one_correct(), one_correct())
    assert r1["n_attempts"] >= 1
    assert r2["n_attempts"] >= 1

    async with factory() as session:
        row = (
            await session.execute(
                select(KCMastery).where(
                    KCMastery.student_id == student_id,
                    KCMastery.knowledge_point == kc_id,
                )
            )
        ).scalar_one()
        n_events = (
            await session.execute(
                select(InteractionEvent).where(
                    InteractionEvent.student_id == student_id,
                    InteractionEvent.knowledge_point == kc_id,
                )
            )
        ).scalars().all()

    assert row.n_attempts == 2, (
        f"lost update: n_attempts={row.n_attempts} (expected 2); "
        f"results={[r1['n_attempts'], r2['n_attempts']]}"
    )
    assert len(n_events) == 2, f"events={len(n_events)}"
    # 两次答对后掌握度应高于先验
    assert row.p_mastery is not None and row.p_mastery > 0.3
