"""U.17 掌握裁决题池物理隔离测试。

裁决题现场生成、不落库；mastery_confirmed 独立于 BKT p_mastery，只由本模块判定写入。
"""

from __future__ import annotations

import uuid
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from obase.config import settings
from services.models import KCMastery, User, UserRole, WrongQuestion
from services.mastery_gate_service import start_gate_check, submit_gate_check
from services.learner_model import MASTERED

KU = "test-gate-ku"


def _mastery_kwargs(p_mastery: float) -> dict:
    return dict(
        p_mastery=p_mastery,
        p_init=0.3,
        p_transit=0.3,
        p_guess=0.15,
        p_slip=0.1,
    )


@pytest.fixture()
async def db_student():
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as db:
        sid = uuid.uuid4()
        db.add(User(id=sid, phone=f"1{str(sid.int)[:10]}", role=UserRole.student))
        await db.commit()
        yield db, sid
        await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
        await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id == sid))
        await db.execute(delete(User).where(User.id == sid))
        await db.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_not_eligible_below_mastered_threshold(db_student):
    db, sid = db_student
    db.add(KCMastery(student_id=sid, knowledge_point=KU, **_mastery_kwargs(0.5)))
    await db.commit()

    result = await start_gate_check(db, sid, KU)
    assert result["eligible"] is False
    assert "MASTERED" not in result["reason"]  # 措辞面向学生，不暴露内部常量名


@pytest.mark.asyncio
async def test_not_eligible_without_base_question(db_student):
    db, sid = db_student
    db.add(
        KCMastery(student_id=sid, knowledge_point=KU, **_mastery_kwargs(MASTERED + 0.1))
    )
    await db.commit()

    result = await start_gate_check(db, sid, KU)
    assert result["eligible"] is False
    assert "暂无可裁决题目" in result["reason"]


@pytest.mark.asyncio
async def test_already_confirmed_short_circuits(db_student):
    db, sid = db_student
    from datetime import datetime, timezone

    db.add(
        KCMastery(
            student_id=sid,
            knowledge_point=KU,
            mastery_confirmed=True,
            mastery_confirmed_at=datetime.now(timezone.utc),
            **_mastery_kwargs(0.9),
        )
    )
    await db.commit()

    result = await start_gate_check(db, sid, KU)
    assert result["eligible"] is True
    assert result["already_confirmed"] is True


@pytest.mark.asyncio
async def test_not_eligible_when_variant_not_kernel_verified(db_student):
    db, sid = db_student
    db.add(
        KCMastery(student_id=sid, knowledge_point=KU, **_mastery_kwargs(MASTERED + 0.1))
    )
    db.add(
        WrongQuestion(
            id=uuid.uuid4(),
            student_id=sid,
            question_text="原题",
            correct_answer="原答案",
            subject="math",
            knowledge_points={KU: 1.0},
        )
    )
    await db.commit()

    unverified = MagicMock(kernel_verified=False, answer="", question="")
    with patch(
        "services.mastery_gate_service.variant_for_review", return_value=unverified
    ):
        result = await start_gate_check(db, sid, KU, caller=object())
    assert result["eligible"] is False
    assert "确定性求解覆盖" in result["reason"]


@pytest.mark.asyncio
async def test_eligible_generates_item_without_leaking_answer(db_student):
    db, sid = db_student
    db.add(
        KCMastery(student_id=sid, knowledge_point=KU, **_mastery_kwargs(MASTERED + 0.1))
    )
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

    verified = MagicMock(kernel_verified=True, answer="2", question="解方程 x+2=4")
    with patch(
        "services.mastery_gate_service.variant_for_review", return_value=verified
    ):
        result = await start_gate_check(db, sid, KU, caller=object())

    assert result["eligible"] is True
    assert result["already_confirmed"] is False
    assert result["item"]["question"] == "解方程 x+2=4"
    assert set(result["item"].keys()) == {"ku_id", "question"}  # 无 answer 字段


@pytest.mark.asyncio
async def test_submit_correct_confirms_mastery_without_touching_bkt(db_student):
    db, sid = db_student
    db.add(
        KCMastery(student_id=sid, knowledge_point=KU, **_mastery_kwargs(MASTERED + 0.1))
    )
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

    verified = MagicMock(kernel_verified=True, answer="4", question="解方程 x+2=6")
    with patch(
        "services.mastery_gate_service.variant_for_review", return_value=verified
    ):
        started = await start_gate_check(db, sid, KU, caller=object())
    assert started["eligible"] is True

    submitted = await submit_gate_check(db, sid, KU, "4")
    assert submitted["verdict"] == "correct"
    assert submitted["mastery_confirmed"] is True

    row = (
        await db.execute(
            select(KCMastery).where(
                KCMastery.student_id == sid, KCMastery.knowledge_point == KU
            )
        )
    ).scalar_one()
    assert row.mastery_confirmed is True
    assert abs(row.p_mastery - (MASTERED + 0.1)) < 1e-9  # BKT 状态未被裁决流程改动


@pytest.mark.asyncio
async def test_submit_wrong_choice_does_not_confirm(db_student):
    """judge_answer 对选择题能明确判"wrong"（自由数值答案则更保守判 unsure，见下一测试）。"""
    db, sid = db_student
    db.add(
        KCMastery(student_id=sid, knowledge_point=KU, **_mastery_kwargs(MASTERED + 0.1))
    )
    db.add(
        WrongQuestion(
            id=uuid.uuid4(),
            student_id=sid,
            question_text="选择题",
            correct_answer="A",
            subject="math",
            knowledge_points={KU: 1.0},
        )
    )
    await db.commit()

    verified = MagicMock(kernel_verified=True, answer="A", question="选择题变式")
    with patch(
        "services.mastery_gate_service.variant_for_review", return_value=verified
    ):
        await start_gate_check(db, sid, KU, caller=object())

    submitted = await submit_gate_check(db, sid, KU, "B")
    assert submitted["verdict"] == "wrong"
    assert submitted["mastery_confirmed"] is False


@pytest.mark.asyncio
async def test_submit_mismatched_freeform_answer_does_not_confirm(db_student):
    """自由数值答案不匹配时 judge_answer 保守判 unsure（宁可不确定不误判），同样不裁决通过。"""
    db, sid = db_student
    db.add(
        KCMastery(student_id=sid, knowledge_point=KU, **_mastery_kwargs(MASTERED + 0.1))
    )
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

    verified = MagicMock(kernel_verified=True, answer="4", question="解方程 x+2=6")
    with patch(
        "services.mastery_gate_service.variant_for_review", return_value=verified
    ):
        await start_gate_check(db, sid, KU, caller=object())

    submitted = await submit_gate_check(db, sid, KU, "999")
    assert submitted["verdict"] == "unsure"
    assert submitted["mastery_confirmed"] is False


@pytest.mark.asyncio
async def test_submit_without_start_reports_expired(db_student):
    db, sid = db_student
    db.add(KCMastery(student_id=sid, knowledge_point=KU, **_mastery_kwargs(0.9)))
    await db.commit()

    result = await submit_gate_check(db, sid, KU, "anything")
    assert result["status"] == "expired"
