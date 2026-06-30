"""item 4：复习检索门。看答案=FSRS Again；提交先检索后判分。直接调服务函数（无 HTTP）。"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from obase.prior_provider import PriorProvider
from services.models import InteractionEvent, KCMastery, MasterySnapshot, User, UserRole, WrongQuestion
from services.review_service import reveal_review_answer, submit_review_answer

KC = "RENJIAO-G7-MATH-S-ku-正数和负数的定义"


@pytest.fixture()
async def db_student_wq():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        sid = uuid.uuid4()
        db.add(User(id=sid, phone=f"1{str(sid.int)[:10]}", role=UserRole.student))
        db.add(WrongQuestion(
            id=uuid.uuid4(), student_id=sid, question_text="x+1=3 求 x",
            correct_answer="2", subject="math", knowledge_points={KC: "x"},
        ))
        await db.flush()
        await PriorProvider.warm_up(db)
        yield db, sid
        await db.execute(delete(InteractionEvent).where(InteractionEvent.student_id == sid))
        await db.execute(delete(MasterySnapshot).where(MasterySnapshot.student_id == sid))
        await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
        await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id == sid))
        await db.execute(delete(User).where(User.id == sid))
        await db.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_reveal_records_fsrs_again(db_student_wq):
    db, sid = db_student_wq
    result = await reveal_review_answer(db, sid, KC)
    await db.commit()
    assert result["recorded_again"] is True
    assert result["answer"] == "2"
    # 最近一次交互的 FSRS 评级应为 Again(=1)
    ev = (await db.execute(
        select(InteractionEvent).where(InteractionEvent.student_id == sid)
        .order_by(InteractionEvent.occurred_at.desc())
    )).scalars().first()
    assert ev is not None
    assert ev.fsrs_rating == 1          # Rating.Again
    assert ev.is_correct is False


@pytest.mark.asyncio
async def test_submit_correct_records_and_returns_answer(db_student_wq):
    db, sid = db_student_wq
    result = await submit_review_answer(db, sid, KC, "2")
    await db.commit()
    assert result["verdict"] == "correct"
    assert result["answer"] == "2"
    row = (await db.execute(
        select(KCMastery).where(KCMastery.student_id == sid)
    )).scalar_one_or_none()
    assert row is not None and row.n_attempts == 1


@pytest.mark.asyncio
async def test_due_list_has_no_answer(db_student_wq):
    """到期复习列表不得携带答案（必须先检索）。"""
    from unittest.mock import patch, MagicMock
    db, sid = db_student_wq
    # 造一张到期卡片
    from oprim.fsrs_engine import fsrs_new_card
    card = fsrs_new_card()
    card["due"] = "2020-01-01T00:00:00+00:00"
    card["last_review"] = "2019-12-01T00:00:00+00:00"
    db.add(KCMastery(
        student_id=sid, knowledge_point=KC, fsrs_card_json=card, p_mastery=0.3,
        p_init=0.2, p_transit=0.2, p_guess=0.15, p_slip=0.12,
    ))
    await db.flush()
    from services.review_service import get_due_variants
    fake_variant = MagicMock(question="变式题？", answer="")
    with patch("services.review_service.variant_for_review", return_value=fake_variant):
        with patch("services.review_service.due_recall_push_workflow", return_value=None):
            items = await get_due_variants(db, sid)
    assert items, "应有到期复习项"
    assert "variant_answer" not in items[0]
    assert items[0].get("requires_retrieval") is True
