"""T.8 周期限时小测（检索检查点）测试。

每 3 天一次；到期/薄弱 KC 池；交错；提交判分回写 BKT/FSRS（source=quiz）；
答错不需要额外"生成复习任务"——FSRS Again 顺延到期即可，验证 fsrs_due 前移。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.auth import create_access_token
from obase.config import settings
from services.main import app
from services.models import (
    InteractionEvent,
    KCMastery,
    MasterySnapshot,
    TimedQuiz,
    User,
    UserRole,
    WrongQuestion,
)
from services.quiz_service import get_or_create_due_quiz, submit_quiz

KU_A = "test-quiz-ku-a"
KU_B = "test-quiz-ku-b"


def _fsrs_card(overdue_days: int) -> dict:
    due = datetime.now(timezone.utc) - timedelta(days=overdue_days)
    return {
        "due": due.isoformat(),
        "stability": 1.0,
        "difficulty": 5.0,
        "elapsed_days": 0,
        "scheduled_days": 1,
        "reps": 1,
        "lapses": 0,
        "state": 2,
        "last_review": due.isoformat(),
    }


@pytest.fixture(scope="function")
async def db():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(scope="function")
async def student(db: AsyncSession):
    sid = uuid.uuid4()
    db.add(
        User(
            id=sid,
            phone=f"188{str(sid)[:8]}",
            role=UserRole.student,
            name="Q",
            grade="高一",
        )
    )
    await db.commit()
    yield sid, create_access_token({"sub": str(sid)})
    await db.execute(delete(TimedQuiz).where(TimedQuiz.student_id == sid))
    await db.execute(delete(InteractionEvent).where(InteractionEvent.student_id == sid))
    await db.execute(delete(MasterySnapshot).where(MasterySnapshot.student_id == sid))
    await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
    await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_not_due_without_due_or_weak_kc(db, student):
    sid, _ = student
    result = await get_or_create_due_quiz(db, sid)
    assert result["due"] is False
    assert "reason" in result


@pytest.mark.asyncio
async def test_due_generates_quiz_from_due_and_weak_kc(db, student):
    sid, _ = student
    db.add(
        KCMastery(
            student_id=sid,
            knowledge_point=KU_A,
            p_mastery=0.8,
            p_init=0.3,
            p_transit=0.3,
            p_guess=0.15,
            p_slip=0.1,
            fsrs_card_json=_fsrs_card(2),
        )
    )
    db.add(
        KCMastery(
            student_id=sid,
            knowledge_point=KU_B,
            p_mastery=0.3,
            p_init=0.3,
            p_transit=0.3,
            p_guess=0.15,
            p_slip=0.1,
        )
    )
    db.add(
        WrongQuestion(
            id=uuid.uuid4(),
            student_id=sid,
            subject="math",
            question_text="题A",
            correct_answer="A",
            knowledge_points={KU_A: 1.0},
        )
    )
    db.add(
        WrongQuestion(
            id=uuid.uuid4(),
            student_id=sid,
            subject="math",
            question_text="题B",
            correct_answer="B",
            knowledge_points={KU_B: 1.0},
        )
    )
    await db.commit()

    result = await get_or_create_due_quiz(db, sid)
    assert result["due"] is True
    assert len(result["items"]) == 2
    kc_ids = {it["kc_id"] for it in result["items"]}
    assert kc_ids == {KU_A, KU_B}
    for it in result["items"]:
        assert "correct_answer" not in it  # 从不返回答案
    assert result["time_limit_seconds"] == 2 * 60


@pytest.mark.asyncio
async def test_not_due_again_within_cadence_window(db, student):
    sid, _ = student
    db.add(
        KCMastery(
            student_id=sid,
            knowledge_point=KU_A,
            p_mastery=0.3,
            p_init=0.3,
            p_transit=0.3,
            p_guess=0.15,
            p_slip=0.1,
        )
    )
    db.add(
        WrongQuestion(
            id=uuid.uuid4(),
            student_id=sid,
            subject="math",
            question_text="题A",
            correct_answer="A",
            knowledge_points={KU_A: 1.0},
        )
    )
    await db.commit()

    first = await get_or_create_due_quiz(db, sid)
    assert first["due"] is True

    second = await get_or_create_due_quiz(db, sid)
    assert second["due"] is False
    assert "next_due_date" in second


@pytest.mark.asyncio
async def test_submit_correct_updates_bkt_and_scores(db, student):
    sid, _ = student
    wq_id = uuid.uuid4()
    db.add(
        KCMastery(
            student_id=sid,
            knowledge_point=KU_A,
            p_mastery=0.3,
            p_init=0.3,
            p_transit=0.3,
            p_guess=0.15,
            p_slip=0.1,
        )
    )
    db.add(
        WrongQuestion(
            id=wq_id,
            student_id=sid,
            subject="math",
            question_text="解方程 x+1=3",
            correct_answer="2",
            knowledge_points={KU_A: 1.0},
        )
    )
    await db.commit()

    quiz = await get_or_create_due_quiz(db, sid)
    result = await submit_quiz(
        db,
        sid,
        uuid.UUID(quiz["quiz_id"]),
        [{"question_id": str(wq_id), "student_answer": "2"}],
        time_spent_seconds=30,
    )

    assert result["score"] == 1.0
    assert result["results"][0]["verdict"] == "correct"
    assert result["failed_kcs"] == []

    ev = (
        await db.execute(
            select(InteractionEvent).where(
                InteractionEvent.student_id == sid, InteractionEvent.source == "quiz"
            )
        )
    ).scalar_one_or_none()
    assert ev is not None
    assert ev.is_correct is True


@pytest.mark.asyncio
async def test_submit_wrong_moves_fsrs_due_closer(db, student):
    """答错的 KC 不需要额外造复习任务：FSRS Again 本身就顺延到近期 due。"""
    sid, _ = student
    wq_id = uuid.uuid4()
    far_future = datetime.now(timezone.utc) + timedelta(days=30)
    db.add(
        KCMastery(
            student_id=sid,
            knowledge_point=KU_A,
            p_mastery=0.3,
            p_init=0.3,
            p_transit=0.3,
            p_guess=0.15,
            p_slip=0.1,
            fsrs_card_json={
                "card_id": 1,
                "state": 2,
                "step": None,
                "stability": 20.0,
                "difficulty": 5.0,
                "due": far_future.isoformat(),
                # >20h 前，避免触发"集中练习去抖"（距上次复习<20h 只更新掌握度不推进
                # 调度，见 cognitive_service._MASSED_PRACTICE_DEBOUNCE_HOURS）
                "last_review": (
                    datetime.now(timezone.utc) - timedelta(days=2)
                ).isoformat(),
            },
        )
    )
    db.add(
        WrongQuestion(
            id=wq_id,
            student_id=sid,
            subject="math",
            question_text="选择题",
            correct_answer="A",  # 选择题 judge_answer 才能判出明确 wrong（自由数值答案
            # 不匹配时保守判 unsure，宁可不确定不误判，见 test_mastery_gate.py 同款教训）
            knowledge_points={KU_A: 1.0},
        )
    )
    await db.commit()

    quiz_id = uuid.uuid4()
    db.add(
        TimedQuiz(
            id=quiz_id,
            student_id=sid,
            items=[
                {
                    "kc_id": KU_A,
                    "question_id": str(wq_id),
                    "question_text": "选择题",
                }
            ],
            time_limit_seconds=60,
        )
    )
    await db.commit()

    result = await submit_quiz(
        db,
        sid,
        quiz_id,
        [{"question_id": str(wq_id), "student_answer": "B"}],
        time_spent_seconds=45,
    )
    assert result["score"] == 0.0
    assert result["failed_kcs"] == [KU_A]

    row = (
        await db.execute(
            select(KCMastery).where(
                KCMastery.student_id == sid, KCMastery.knowledge_point == KU_A
            )
        )
    ).scalar_one()
    # KCMastery 的更新走 Core 层 upsert（PgStore），不经过本 session 已加载对象的
    # identity map 自动同步——显式 refresh 才能看到 process_interaction 刚写入的新值。
    await db.refresh(row)
    new_due = datetime.fromisoformat(row.fsrs_card_json["due"])
    assert new_due < far_future  # Again 评级顺延到更近的 due，不再是 30 天后


@pytest.mark.asyncio
async def test_submit_twice_rejected(db, student):
    sid, _ = student
    wq_id = uuid.uuid4()
    db.add(
        KCMastery(
            student_id=sid,
            knowledge_point=KU_A,
            p_mastery=0.3,
            p_init=0.3,
            p_transit=0.3,
            p_guess=0.15,
            p_slip=0.1,
        )
    )
    db.add(
        WrongQuestion(
            id=wq_id,
            student_id=sid,
            subject="math",
            question_text="解方程 x+1=3",
            correct_answer="2",
            knowledge_points={KU_A: 1.0},
        )
    )
    await db.commit()
    quiz = await get_or_create_due_quiz(db, sid)
    quiz_id = uuid.UUID(quiz["quiz_id"])

    await submit_quiz(
        db, sid, quiz_id, [{"question_id": str(wq_id), "student_answer": "2"}], 30
    )
    second = await submit_quiz(
        db, sid, quiz_id, [{"question_id": str(wq_id), "student_answer": "2"}], 30
    )
    assert "error" in second


@pytest.mark.asyncio
async def test_quiz_due_and_submit_api(db, student):
    sid, token = student
    wq_id = uuid.uuid4()
    db.add(
        KCMastery(
            student_id=sid,
            knowledge_point=KU_A,
            p_mastery=0.3,
            p_init=0.3,
            p_transit=0.3,
            p_guess=0.15,
            p_slip=0.1,
        )
    )
    db.add(
        WrongQuestion(
            id=wq_id,
            student_id=sid,
            subject="math",
            question_text="解方程 x+1=3",
            correct_answer="2",
            knowledge_points={KU_A: 1.0},
        )
    )
    await db.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        due_resp = await c.get(f"/v1/quiz/due/{sid}", headers=_headers(token))
        assert due_resp.status_code == 200
        due = due_resp.json()
        assert due["due"] is True
        quiz_id = due["quiz_id"]

        submit_resp = await c.post(
            f"/v1/quiz/{quiz_id}/submit",
            params={"student_id": str(sid)},
            json={
                "answers": [{"question_id": str(wq_id), "student_answer": "2"}],
                "time_spent_seconds": 20,
            },
            headers=_headers(token),
        )
    assert submit_resp.status_code == 200
    assert submit_resp.json()["score"] == 1.0

    # 端点用的是自己 Depends(get_db) 注入的另一个 session，重新查一次验证真落库
    row = (
        await db.execute(select(TimedQuiz).where(TimedQuiz.id == uuid.UUID(quiz_id)))
    ).scalar_one()
    assert row.submitted_at is not None
    assert row.score == 1.0
