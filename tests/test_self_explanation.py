"""自我解释采集（教育理念 04·Chi 效应）：process_interaction 透传落 interaction_events，
纯采集不影响判分/掌握度。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from obase.prior_provider import PriorProvider
from services.cognitive_service import process_interaction
from services.models import InteractionEvent, KCMastery, MasterySnapshot, User, UserRole

KC = "RENJIAO-G7-MATH-S-ku-正数和负数的定义"


@pytest.fixture()
async def db_student():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as db:
        sid = uuid.uuid4()
        db.add(User(id=sid, phone=f"1{str(sid.int)[:10]}", role=UserRole.student))
        await db.flush()
        await PriorProvider.warm_up(db)
        yield db, sid
        await db.execute(
            delete(InteractionEvent).where(InteractionEvent.student_id == sid)
        )
        await db.execute(
            delete(MasterySnapshot).where(MasterySnapshot.student_id == sid)
        )
        await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
        await db.execute(delete(User).where(User.id == sid))
        await db.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_self_explanation_persisted(db_student):
    db, sid = db_student
    now = datetime.now(timezone.utc)
    await process_interaction(
        db,
        student_id=sid,
        kc_id=KC,
        is_correct=True,
        self_explanation="因为负号表示相反方向，所以 -3 在 0 左边",
        now=now,
    )
    await db.commit()
    ev = (
        (
            await db.execute(
                select(InteractionEvent)
                .where(InteractionEvent.student_id == sid)
                .order_by(InteractionEvent.occurred_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert ev is not None
    assert ev.self_explanation == "因为负号表示相反方向，所以 -3 在 0 左边"
    # 纯采集：不影响正误
    assert ev.is_correct is True


@pytest.mark.asyncio
async def test_no_self_explanation_leaves_null(db_student):
    db, sid = db_student
    await process_interaction(db, student_id=sid, kc_id=KC, is_correct=False)
    await db.commit()
    ev = (
        (
            await db.execute(
                select(InteractionEvent)
                .where(InteractionEvent.student_id == sid)
                .order_by(InteractionEvent.occurred_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert ev is not None and ev.self_explanation is None
