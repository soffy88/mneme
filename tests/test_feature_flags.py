"""U.24 教学机制 feature-flag 化：验证每个 pedagogy 开关设为 "0" 后机制真的关闭
（默认开=保留现状已由其余测试覆盖，这里专测"关"这条此前完全没测过的路径）。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.auth import create_access_token
from obase.config import settings
from services.cognitive_service import process_interaction
from services.daily_plan_service import build_daily_plan
from services.main import app
from services.models import (
    InteractionEvent,
    KCMastery,
    MasterySnapshot,
    User,
    UserRole,
    WrongQuestion,
)

KU = "test-flags-ku"


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
            phone=f"166{str(sid)[:8]}",
            role=UserRole.student,
            name="F",
            grade="高一",
        )
    )
    await db.commit()
    yield sid, create_access_token({"sub": str(sid)})
    await db.execute(delete(InteractionEvent).where(InteractionEvent.student_id == sid))
    await db.execute(delete(MasterySnapshot).where(MasterySnapshot.student_id == sid))
    await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
    await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── 01 fringe ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fringe_disabled_omits_field(student, monkeypatch):
    monkeypatch.setenv("PEDAGOGY_FRINGE_ENABLED", "0")
    sid, token = student
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(
            "/v1/knowledge-points",
            params={"student_id": str(sid)},
            headers=_h(token),
        )
    assert r.status_code == 200
    assert all(item["fringe"] is None for item in r.json())


# ── 02 league ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_league_disabled_returns_404(student, monkeypatch):
    monkeypatch.setenv("PEDAGOGY_LEAGUE_ENABLED", "0")
    sid, token = student
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(f"/v1/league/{sid}", headers=_h(token))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_league_enabled_by_default(student):
    sid, token = student
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(f"/v1/league/{sid}", headers=_h(token))
    assert r.status_code == 200


# ── 03 OLM ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_olm_disabled_returns_404(student, monkeypatch):
    monkeypatch.setenv("PEDAGOGY_OLM_ENABLED", "0")
    sid, token = student
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(f"/v1/learner-model/{sid}/{KU}", headers=_h(token))
    assert r.status_code == 404


# ── 04 self-explanation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_self_explanation_disabled_is_not_persisted(db, student, monkeypatch):
    monkeypatch.setenv("PEDAGOGY_SELF_EXPLANATION_ENABLED", "0")
    sid, _ = student
    await process_interaction(
        db,
        student_id=sid,
        kc_id=KU,
        is_correct=True,
        question_type="solve",
        source="quick",
        self_explanation="因为这样代入之后两边相等",
    )
    await db.commit()
    from sqlalchemy import select

    ev = (
        await db.execute(
            select(InteractionEvent).where(
                InteractionEvent.student_id == sid,
                InteractionEvent.knowledge_point == KU,
            )
        )
    ).scalar_one()
    assert ev.self_explanation is None


@pytest.mark.asyncio
async def test_self_explanation_enabled_by_default_is_persisted(db, student):
    sid, _ = student
    await process_interaction(
        db,
        student_id=sid,
        kc_id=KU,
        is_correct=True,
        question_type="solve",
        source="quick",
        self_explanation="因为这样代入之后两边相等",
    )
    await db.commit()
    from sqlalchemy import select

    ev = (
        await db.execute(
            select(InteractionEvent).where(
                InteractionEvent.student_id == sid,
                InteractionEvent.knowledge_point == KU,
            )
        )
    ).scalar_one()
    assert ev.self_explanation == "因为这样代入之后两边相等"


# ── 05 growth feedback ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_growth_feedback_disabled_is_none(db, student, monkeypatch):
    monkeypatch.setenv("PEDAGOGY_GROWTH_FEEDBACK_ENABLED", "0")
    sid, _ = student
    result = await process_interaction(
        db,
        student_id=sid,
        kc_id=KU,
        is_correct=True,
        question_type="solve",
        source="quick",
    )
    await db.commit()
    assert result["growth_message"] is None


@pytest.mark.asyncio
async def test_growth_feedback_enabled_by_default(db, student):
    sid, _ = student
    result = await process_interaction(
        db,
        student_id=sid,
        kc_id=KU,
        is_correct=True,
        question_type="solve",
        source="quick",
    )
    await db.commit()
    assert result["growth_message"] is not None


# ── 06 exam-aware scheduling ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exam_aware_disabled_ignores_exam_date(db, student, monkeypatch):
    from datetime import date, datetime, timezone
    from sqlalchemy import update

    monkeypatch.setenv("PEDAGOGY_EXAM_AWARE_ENABLED", "0")
    sid, _ = student
    await db.execute(
        update(User).where(User.id == sid).values(exam_date=date(2026, 7, 5))
    )
    await db.commit()

    plan = await build_daily_plan(
        db, sid, now=datetime(2026, 7, 4, tzinfo=timezone.utc)
    )
    assert plan["exam_countdown_days"] is None
    assert plan["near_exam"] is False


@pytest.mark.asyncio
async def test_exam_aware_enabled_by_default_computes_countdown(db, student):
    from datetime import date, datetime, timezone
    from sqlalchemy import update

    sid, _ = student
    await db.execute(
        update(User).where(User.id == sid).values(exam_date=date(2026, 7, 5))
    )
    await db.commit()

    plan = await build_daily_plan(
        db, sid, now=datetime(2026, 7, 4, tzinfo=timezone.utc)
    )
    assert plan["exam_countdown_days"] == 1
    assert plan["near_exam"] is True


# ── 07 刻意练习细颗粒反馈 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fine_feedback_disabled_skips_step_analysis(student, monkeypatch, db):
    monkeypatch.setenv("PEDAGOGY_FINE_FEEDBACK_ENABLED", "0")
    sid, token = student
    wq_id = uuid.uuid4()
    db.add(
        WrongQuestion(
            id=wq_id,
            student_id=None,
            subject="math",
            question_text="选择题",
            correct_answer="A",
            knowledge_points={KU: 1.0},
        )
    )
    await db.commit()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/v1/practice/submit",
            json={
                "student_id": str(sid),
                "ku_id": KU,
                "question_id": str(wq_id),
                "student_answer": "B",
                "student_steps": ["第一步", "第二步"],
            },
            headers=_h(token),
        )
    assert r.status_code == 200
    assert r.json()["step_analysis"] is None
    await db.execute(delete(WrongQuestion).where(WrongQuestion.id == wq_id))
    await db.commit()


# ── 08 affect ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_affect_disabled_returns_404(student, monkeypatch):
    monkeypatch.setenv("PEDAGOGY_AFFECT_ENABLED", "0")
    sid, token = student
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(f"/v1/affect/{sid}", headers=_h(token))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_affect_enabled_by_default(student):
    sid, token = student
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(f"/v1/affect/{sid}", headers=_h(token))
    assert r.status_code == 200
