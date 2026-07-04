"""U.18 迁移探针题池测试。

迁移探针现场生成（不落库、不进练习池），独立于常规变式的 generate_variants 参数；
判分时按 Redis 缓存识别 source=transfer_probe，接入学习层"迁移率"指标。
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import patch, MagicMock

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
from services.learner_model import MASTERED
from services.transfer_probe_service import (
    transfer_probe_gate,
    maybe_build_transfer_probe,
)
from services.review_service import get_due_variants, submit_review_answer

KU = "test-transfer-ku"


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
        await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id == sid))
        await db.execute(delete(User).where(User.id == sid))
        await db.commit()
    await engine.dispose()


def test_gate_is_deterministic():
    sid = uuid.uuid4()
    d = date(2026, 7, 4)
    assert transfer_probe_gate(sid, d) == transfer_probe_gate(sid, d)


@pytest.mark.asyncio
async def test_returns_none_when_gate_closed(db_student):
    db, sid = db_student
    db.add(
        KCMastery(
            student_id=sid,
            knowledge_point=KU,
            p_mastery=0.9,
            p_init=0.3,
            p_transit=0.3,
            p_guess=0.15,
            p_slip=0.1,
        )
    )
    await db.commit()

    with patch(
        "services.transfer_probe_service.transfer_probe_gate", return_value=False
    ):
        result = await maybe_build_transfer_probe(db, sid, [], caller=object())
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_without_mastered_ku(db_student):
    db, sid = db_student
    with patch(
        "services.transfer_probe_service.transfer_probe_gate", return_value=True
    ):
        result = await maybe_build_transfer_probe(db, sid, [], caller=object())
    assert result is None


@pytest.mark.asyncio
async def test_returns_none_when_variant_not_verified(db_student):
    db, sid = db_student
    m = KCMastery(
        student_id=sid,
        knowledge_point=KU,
        p_mastery=MASTERED + 0.1,
        p_init=0.3,
        p_transit=0.3,
        p_guess=0.15,
        p_slip=0.1,
    )
    db.add(m)
    db.add(
        WrongQuestion(
            id=uuid.uuid4(),
            student_id=sid,
            question_text="原题",
            correct_answer="2",
            subject="math",
            knowledge_points={KU: 1.0},
        )
    )
    await db.commit()

    unverified = MagicMock(kernel_verified=False, answer="", question="")
    with (
        patch("services.transfer_probe_service.transfer_probe_gate", return_value=True),
        patch(
            "services.transfer_probe_service.variant_for_review",
            return_value=unverified,
        ),
    ):
        result = await maybe_build_transfer_probe(db, sid, [m], caller=object())
    assert result is None


@pytest.mark.asyncio
async def test_builds_item_and_caches_answer_when_eligible(db_student):
    db, sid = db_student
    m = KCMastery(
        student_id=sid,
        knowledge_point=KU,
        p_mastery=MASTERED + 0.1,
        p_init=0.3,
        p_transit=0.3,
        p_guess=0.15,
        p_slip=0.1,
    )
    db.add(m)
    db.add(
        WrongQuestion(
            id=uuid.uuid4(),
            student_id=sid,
            question_text="解方程 x+1=3",
            correct_answer="2",
            subject="math",
            knowledge_points={KU: 1.0},
        )
    )
    await db.commit()

    verified = MagicMock(
        kernel_verified=True, answer="7", question="一个新情境下的等价问题"
    )
    with (
        patch("services.transfer_probe_service.transfer_probe_gate", return_value=True),
        patch(
            "services.transfer_probe_service.variant_for_review", return_value=verified
        ),
    ):
        result = await maybe_build_transfer_probe(db, sid, [m], caller=object())

    assert result is not None
    assert result["kc_id"] == KU
    assert result["variant_question"] == "一个新情境下的等价问题"
    assert result["is_transfer_probe"] is True
    assert "answer" not in result


@pytest.mark.asyncio
async def test_end_to_end_due_queue_and_grading(db_student):
    """混进 get_due_variants 队列 → 判分识别 source=transfer_probe，按新答案（非原题答案）判分。"""
    db, sid = db_student
    m = KCMastery(
        student_id=sid,
        knowledge_point=KU,
        p_mastery=MASTERED + 0.1,
        p_init=0.3,
        p_transit=0.3,
        p_guess=0.15,
        p_slip=0.1,
    )
    db.add(m)
    db.add(
        WrongQuestion(
            id=uuid.uuid4(),
            student_id=sid,
            question_text="解方程 x+1=3",
            correct_answer="2",
            subject="math",
            knowledge_points={KU: 1.0},
        )
    )
    await db.commit()

    verified = MagicMock(kernel_verified=True, answer="99", question="迁移探针新题")
    with (
        patch("services.transfer_probe_service.transfer_probe_gate", return_value=True),
        patch(
            "services.transfer_probe_service.variant_for_review", return_value=verified
        ),
    ):
        items = await get_due_variants(db, sid)

    probe_items = [it for it in items if it.get("is_transfer_probe")]
    assert len(probe_items) == 1
    assert probe_items[0]["kc_id"] == KU

    # 判分：正确答案应为探针的 "99"（新变式答案），不是原题的 "2"
    result = await submit_review_answer(db, sid, KU, "99")
    await db.commit()
    assert result["verdict"] == "correct"
    assert result["answer"] == "99"

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
    assert ev.source.value == "transfer_probe"


@pytest.mark.asyncio
async def test_learning_metrics_reflects_transfer_probe_accuracy(db_student):
    from services.learning_metrics_service import compute_learning_metrics
    from services.cognitive_service import process_interaction

    db, sid = db_student
    db.add(
        KCMastery(
            student_id=sid,
            knowledge_point=KU,
            p_mastery=MASTERED + 0.1,
            p_init=0.3,
            p_transit=0.3,
            p_guess=0.15,
            p_slip=0.1,
        )
    )
    await db.commit()

    await process_interaction(
        db,
        student_id=sid,
        kc_id=KU,
        is_correct=True,
        question_type="solve",
        source="transfer_probe",
    )
    await db.commit()

    m = await compute_learning_metrics(db)
    assert m["transfer_rate"] is not None
    assert m["transfer_rate_n"] >= 1
