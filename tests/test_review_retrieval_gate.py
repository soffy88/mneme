"""item 4：复习检索门。看答案=FSRS Again；提交先检索后判分。直接调服务函数（无 HTTP）。"""

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
    User,
    UserRole,
    WrongQuestion,
)
from services.review_service import reveal_review_answer, submit_review_answer

KC = "RENJIAO-G7-MATH-S-ku-正数和负数的定义"


@pytest.fixture()
async def db_student_wq():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as db:
        sid = uuid.uuid4()
        db.add(User(id=sid, phone=f"1{str(sid.int)[:10]}", role=UserRole.student))
        db.add(
            WrongQuestion(
                id=uuid.uuid4(),
                student_id=sid,
                question_text="x+1=3 求 x",
                correct_answer="2",
                subject="math",
                knowledge_points={KC: "x"},
            )
        )
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
    assert ev.fsrs_rating == 1  # Rating.Again
    assert ev.is_correct is False


@pytest.mark.asyncio
async def test_submit_correct_records_and_returns_answer(db_student_wq):
    db, sid = db_student_wq
    result = await submit_review_answer(db, sid, KC, "2")
    await db.commit()
    assert result["verdict"] == "correct"
    assert result["answer"] == "2"
    row = (
        await db.execute(select(KCMastery).where(KCMastery.student_id == sid))
    ).scalar_one_or_none()
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
    db.add(
        KCMastery(
            student_id=sid,
            knowledge_point=KC,
            fsrs_card_json=card,
            p_mastery=0.3,
            p_init=0.2,
            p_transit=0.2,
            p_guess=0.15,
            p_slip=0.12,
        )
    )
    await db.flush()
    from services.review_service import get_due_variants

    fake_variant = MagicMock(question="变式题？", answer="")
    with patch("services.review_service.variant_for_review", return_value=fake_variant):
        with patch(
            "services.review_service.due_recall_push_workflow", return_value=None
        ):
            items = await get_due_variants(db, sid)
    assert items, "应有到期复习项"
    assert "variant_answer" not in items[0]
    assert items[0].get("requires_retrieval") is True


@pytest.mark.asyncio
async def test_due_item_survives_variant_failure(db_student_wq):
    """变式生成失败不丢到期项（回退原题面）。"""
    from unittest.mock import patch
    from oprim.fsrs_engine import fsrs_new_card
    from services.review_service import get_due_variants

    db, sid = db_student_wq
    card = fsrs_new_card()
    card["due"] = "2020-01-01T00:00:00+00:00"
    card["last_review"] = "2019-12-01T00:00:00+00:00"
    db.add(
        KCMastery(
            student_id=sid,
            knowledge_point=KC,
            fsrs_card_json=card,
            p_mastery=0.3,
            p_init=0.2,
            p_transit=0.2,
            p_guess=0.15,
            p_slip=0.12,
        )
    )
    await db.flush()
    with patch(
        "services.review_service.variant_for_review",
        side_effect=RuntimeError("LLM down"),
    ):
        with patch(
            "services.review_service.due_recall_push_workflow", return_value=None
        ):
            items = await get_due_variants(db, sid)
    assert items, "变式失败也不应丢到期项"
    assert items[0]["ku_id"] == KC
    assert items[0]["variant_question"]  # 回退到原题面，非空


@pytest.mark.asyncio
async def test_unverified_variant_degrades_to_original_and_judges_consistently(
    db_student_wq,
):
    """红线 P0-5：未内核验证的变式（数值改了）不得展示——降级同题复现，
    判分用原题答案，且判分与**展示的题面**一致（绝不拿原答案判改了数值的题）。"""
    from unittest.mock import MagicMock, patch

    from oprim.fsrs_engine import fsrs_new_card
    from services.review_service import get_due_variants, submit_review_answer

    db, sid = db_student_wq
    card = fsrs_new_card()
    card["due"] = "2020-01-01T00:00:00+00:00"
    card["last_review"] = "2019-12-01T00:00:00+00:00"
    db.add(
        KCMastery(
            student_id=sid,
            knowledge_point=KC,
            fsrs_card_json=card,
            p_mastery=0.3,
            p_init=0.2,
            p_transit=0.2,
            p_guess=0.15,
            p_slip=0.12,
        )
    )
    await db.flush()

    # LLM 变式：数值不同（答案 15），但内核未验证
    bad_variant = MagicMock(question="x+5=20 求 x", answer="15", kernel_verified=False)
    with patch("services.review_service.variant_for_review", return_value=bad_variant):
        with patch(
            "services.review_service.due_recall_push_workflow", return_value=None
        ):
            items = await get_due_variants(db, sid, generate_variants=True)

    assert items and items[0]["ku_id"] == KC
    # 展示的必须是原题面（同题复现），不是被 LLM 改了数值的变式
    assert items[0]["variant_question"] == "x+1=3 求 x"
    assert items[0]["answer_source"] == "original"
    # 判分与展示题面一致：原题答案 2 判对；变式答案 15 判错（未误判）
    assert (await submit_review_answer(db, sid, KC, "2"))["verdict"] == "correct"
    assert (await submit_review_answer(db, sid, KC, "15"))["verdict"] != "correct"
    await db.commit()


@pytest.mark.asyncio
async def test_kernel_verified_variant_shown_and_judged_by_its_own_answer(
    db_student_wq,
):
    """红线 P0-5：内核已验证的变式才展示变式题面，且判分用**变式自身的内核答案**
    （经 Redis 携带），不再回退原题答案。"""
    from unittest.mock import MagicMock, patch

    from oprim.fsrs_engine import fsrs_new_card
    from services.review_service import get_due_variants, submit_review_answer

    db, sid = db_student_wq
    card = fsrs_new_card()
    card["due"] = "2020-01-01T00:00:00+00:00"
    card["last_review"] = "2019-12-01T00:00:00+00:00"
    db.add(
        KCMastery(
            student_id=sid,
            knowledge_point=KC,
            fsrs_card_json=card,
            p_mastery=0.3,
            p_init=0.2,
            p_transit=0.2,
            p_guess=0.15,
            p_slip=0.12,
        )
    )
    await db.flush()

    good_variant = MagicMock(question="x+5=20 求 x", answer="15", kernel_verified=True)
    with patch("services.review_service.variant_for_review", return_value=good_variant):
        with patch(
            "services.review_service.due_recall_push_workflow", return_value=None
        ):
            items = await get_due_variants(db, sid, generate_variants=True)

    assert items[0]["variant_question"] == "x+5=20 求 x"
    assert items[0]["answer_source"] == "kernel"
    # 判分用变式自己的内核答案 15（对），原题答案 2 现在算错
    assert (await submit_review_answer(db, sid, KC, "15"))["verdict"] == "correct"
    assert (await submit_review_answer(db, sid, KC, "2"))["verdict"] != "correct"
    await db.commit()
