"""
end_session BKT/FSRS 触发测试

验证 end_session() 在各 outcome 下正确写入 kc_mastery / interaction_events。
- success  → is_correct=True,  kc_updated=True
- failed   → is_correct=False, struggled=True, kc_updated=True
- abandoned → kc_updated=False, 不写 interaction_events
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from obase.prior_provider import PriorProvider
from services.models import (
    InteractionEvent,
    KCMastery,
    MasterySnapshot,
    SocraticMode,
    SocraticSession,
    User,
    UserRole,
    WrongQuestion,
)
from services.socratic_service import end_session

KU_ID = "RENJIAO-G7-MATH-S-ku-正数和负数的定义"


@pytest.fixture()
async def session_with_student_and_wq():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as db:
        student_id = uuid.uuid4()
        phone = f"1{str(student_id.int)[:10]}"
        user = User(id=student_id, phone=phone, role=UserRole.student)
        db.add(user)

        wq_id = uuid.uuid4()
        wq = WrongQuestion(
            id=wq_id,
            student_id=student_id,
            question_text="负数的定义是什么？",
            subject="math",
            knowledge_points={KU_ID: "正数和负数的定义"},
        )
        db.add(wq)
        await db.flush()
        await PriorProvider.warm_up(db)

        yield db, student_id, wq_id

        # teardown
        await db.execute(delete(SocraticSession).where(SocraticSession.student_id == student_id))
        await db.execute(delete(InteractionEvent).where(InteractionEvent.student_id == student_id))
        await db.execute(delete(MasterySnapshot).where(MasterySnapshot.student_id == student_id))
        await db.execute(delete(KCMastery).where(KCMastery.student_id == student_id))
        await db.execute(delete(WrongQuestion).where(WrongQuestion.id == wq_id))
        await db.execute(delete(User).where(User.id == student_id))
        await db.commit()

    await engine.dispose()


async def _make_session(db: AsyncSession, student_id: uuid.UUID, wq_id: uuid.UUID) -> uuid.UUID:
    sess_id = uuid.uuid4()
    ss = SocraticSession(
        id=sess_id,
        student_id=student_id,
        question_id=wq_id,
        mode=SocraticMode.deep,
        messages=[],
        emotion_log=[],
        used_escape_hatch=False,
    )
    db.add(ss)
    await db.flush()
    return sess_id


@pytest.mark.asyncio
async def test_end_session_success_writes_kc_mastery(session_with_student_and_wq):
    db, student_id, wq_id = session_with_student_and_wq

    sess_id = await _make_session(db, student_id, wq_id)
    result = await end_session(db, sess_id, "success")
    await db.commit()

    assert result["kc_updated"] is True
    assert result["outcome"] == "success"

    row = (await db.execute(
        select(KCMastery)
        .where(KCMastery.student_id == student_id)
        .where(KCMastery.knowledge_point == KU_ID)
    )).scalar_one_or_none()
    assert row is not None, "kc_mastery 应已创建"
    assert row.n_attempts == 1
    assert row.p_mastery is not None and row.p_mastery > 0


@pytest.mark.asyncio
async def test_end_session_failed_writes_incorrect_event(session_with_student_and_wq):
    db, student_id, wq_id = session_with_student_and_wq

    sess_id = await _make_session(db, student_id, wq_id)
    result = await end_session(db, sess_id, "failed")
    await db.commit()

    assert result["kc_updated"] is True

    event = (await db.execute(
        select(InteractionEvent)
        .where(InteractionEvent.student_id == student_id)
        .where(InteractionEvent.knowledge_point == KU_ID)
    )).scalar_one_or_none()
    assert event is not None
    assert event.is_correct is False
    assert event.source.value == "socratic"


@pytest.mark.asyncio
async def test_end_session_abandoned_skips_kc_update(session_with_student_and_wq):
    db, student_id, wq_id = session_with_student_and_wq

    sess_id = await _make_session(db, student_id, wq_id)
    result = await end_session(db, sess_id, "abandoned")
    await db.commit()

    assert result["kc_updated"] is False

    row = (await db.execute(
        select(KCMastery)
        .where(KCMastery.student_id == student_id)
        .where(KCMastery.knowledge_point == KU_ID)
    )).scalar_one_or_none()
    assert row is None, "abandoned 不应写入 kc_mastery"

    events = (await db.execute(
        select(InteractionEvent).where(InteractionEvent.student_id == student_id)
    )).scalars().all()
    assert len(events) == 0, "abandoned 不应写入 interaction_events"
