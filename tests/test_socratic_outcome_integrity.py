"""item 9：苏格拉底 outcome 服务端核实（防前端伪报 success 污染 BKT）。"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

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
async def db_wq_with_answer():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        student_id = uuid.uuid4()
        user = User(id=student_id, phone=f"1{str(student_id.int)[:10]}", role=UserRole.student)
        db.add(user)
        wq_id = uuid.uuid4()
        db.add(WrongQuestion(
            id=wq_id, student_id=student_id, question_text="求 x：x+1=3",
            correct_answer="2", subject="math",
            knowledge_points={KU_ID: "正数和负数的定义"},
        ))
        await db.flush()
        await PriorProvider.warm_up(db)
        yield db, student_id, wq_id
        await db.execute(delete(SocraticSession).where(SocraticSession.student_id == student_id))
        await db.execute(delete(InteractionEvent).where(InteractionEvent.student_id == student_id))
        await db.execute(delete(MasterySnapshot).where(MasterySnapshot.student_id == student_id))
        await db.execute(delete(KCMastery).where(KCMastery.student_id == student_id))
        await db.execute(delete(WrongQuestion).where(WrongQuestion.id == wq_id))
        await db.execute(delete(User).where(User.id == student_id))
        await db.commit()
    await engine.dispose()


async def _mk(db, student_id, wq_id, messages):
    sid = uuid.uuid4()
    db.add(SocraticSession(
        id=sid, student_id=student_id, question_id=wq_id, mode=SocraticMode.deep,
        messages=messages, emotion_log=[], used_escape_hatch=False,
    ))
    await db.flush()
    return sid


@pytest.mark.asyncio
async def test_unverified_success_downgraded(db_wq_with_answer):
    """客户端报 success，但对话里没出现正确答案 → 降级 partial，不更新 BKT。"""
    db, student_id, wq_id = db_wq_with_answer
    sid = await _mk(db, student_id, wq_id, [{"role": "user", "content": "我觉得是 5"}])
    result = await end_session(db, sid, "success")
    await db.commit()
    assert result["verified_success"] is False
    assert result["outcome"] == "partial"
    assert result["kc_updated"] is False
    row = (await db.execute(
        select(KCMastery).where(KCMastery.student_id == student_id)
    )).scalar_one_or_none()
    assert row is None, "未核实的 success 不得写掌握度"


@pytest.mark.asyncio
async def test_verified_success_credits(db_wq_with_answer):
    """对话里学生说出正确答案 → 核实 success，更新 BKT。"""
    db, student_id, wq_id = db_wq_with_answer
    sid = await _mk(db, student_id, wq_id, [{"role": "user", "content": "x = 2"}])
    result = await end_session(db, sid, "success")
    await db.commit()
    assert result["verified_success"] is True
    assert result["outcome"] == "success"
    assert result["kc_updated"] is True


@pytest.mark.asyncio
async def test_verified_overrides_client_partial(db_wq_with_answer):
    """学生其实答对了（客户端只报 partial）→ 服务端核实后仍记 success。"""
    db, student_id, wq_id = db_wq_with_answer
    sid = await _mk(db, student_id, wq_id, [{"role": "user", "content": "应该是 2"}])
    result = await end_session(db, sid, "partial")
    await db.commit()
    assert result["outcome"] == "success"
    assert result["kc_updated"] is True
