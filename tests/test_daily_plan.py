"""
每日计划规则引擎测试 — Epic O.2

造测试数据验证优先级排序：
- P1 FSRS到期复习
- P2 错题巩固
- P3 薄弱知识点
- P4 新知识点（遵守 prerequisites）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from obase.auth import create_access_token
from services.main import app
from services.models import (
    KCMastery,
    KnowledgeCluster,
    KnowledgeUnit,
    Textbook,
    User,
    UserRole,
    WrongQuestion,
)
from services.daily_plan_service import build_daily_plan

# ── fixtures ─────────────────────────────────────────────────────────────────


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
            phone=f"177{str(sid)[:8]}",
            role=UserRole.student,
            name="P",
            grade="高一",
        )
    )
    await db.commit()
    yield sid
    await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id == sid))
    await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.fixture(scope="function")
async def ku_seed(db: AsyncSession):
    """2 cluster / 4 KU: ku_a(no prereq), ku_b(prereq:ku_a), ku_c(no prereq), ku_d(prereq:ku_b)"""
    tb_id = f"test-tb-plan-{uuid.uuid4().hex[:6]}"
    c1_id = f"test-c1-plan-{uuid.uuid4().hex[:6]}"
    ku_a = f"test-ku-a-{uuid.uuid4().hex[:6]}"
    ku_b = f"test-ku-b-{uuid.uuid4().hex[:6]}"
    ku_c = f"test-ku-c-{uuid.uuid4().hex[:6]}"
    ku_d = f"test-ku-d-{uuid.uuid4().hex[:6]}"

    db.add(
        Textbook(
            id=tb_id,
            subject="math",
            grade="高一",
            edition="测试版",
            book_name="计划测试教材",
        )
    )
    await db.flush()
    db.add(
        KnowledgeCluster(id=c1_id, textbook_id=tb_id, name="测试章节", display_order=1)
    )
    await db.flush()

    for ku_id, prereqs, diff in [
        (ku_a, [], 0.3),
        (ku_b, [ku_a], 0.4),
        (ku_c, [], 0.3),
        (ku_d, [ku_b], 0.6),
    ]:
        db.add(
            KnowledgeUnit(
                id=ku_id,
                textbook_id=tb_id,
                cluster_id=c1_id,
                name=f"KU-{ku_id[-6:]}",
                description="测试",
                prerequisites=prereqs,
                related_kus=[],
                difficulty=diff,
                exam_frequency="mid",
                question_types=["选择题"],
                ku_type="concept",
                mastery_levels=[],
            )
        )
    await db.commit()

    yield {
        "tb_id": tb_id,
        "c1": c1_id,
        "ku_a": ku_a,
        "ku_b": ku_b,
        "ku_c": ku_c,
        "ku_d": ku_d,
    }

    await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.textbook_id == tb_id))
    await db.execute(
        delete(KnowledgeCluster).where(KnowledgeCluster.textbook_id == tb_id)
    )
    await db.execute(delete(Textbook).where(Textbook.id == tb_id))
    await db.commit()


def _fsrs_card(overdue_days: int) -> dict:
    """Create a FSRS card dict that is overdue by N days."""
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


def _fsrs_future_card(days_ahead: int) -> dict:
    """Create a FSRS card dict that is NOT yet due."""
    due = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    return {
        "due": due.isoformat(),
        "stability": 10.0,
        "difficulty": 3.0,
        "elapsed_days": 0,
        "scheduled_days": days_ahead,
        "reps": 3,
        "lapses": 0,
        "state": 2,
        "last_review": datetime.now(timezone.utc).isoformat(),
    }


def _token(student_id: uuid.UUID) -> str:
    return create_access_token({"sub": str(student_id)})


# ── P1 tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_p1_fsrs_due_generates_review_task(db, student):
    db.add(
        KCMastery(
            student_id=student,
            knowledge_point="GDMATH-SET-01",
            p_mastery=0.7,
            p_init=0.45,
            p_transit=0.35,
            p_guess=0.25,
            p_slip=0.08,
            fsrs_card_json=_fsrs_card(overdue_days=3),
        )
    )
    await db.commit()

    plan = await build_daily_plan(db, student)
    review_tasks = [t for t in plan["tasks"] if t["type"] == "review"]
    assert len(review_tasks) == 1
    assert review_tasks[0]["priority"] == 1
    assert "GDMATH-SET-01" in review_tasks[0]["ku_ids"]
    assert review_tasks[0]["estimated_minutes"] > 0


@pytest.mark.asyncio
async def test_p1_not_due_no_review_task(db, student):
    db.add(
        KCMastery(
            student_id=student,
            knowledge_point="GDMATH-SET-02",
            p_mastery=0.8,
            p_init=0.45,
            p_transit=0.35,
            p_guess=0.25,
            p_slip=0.08,
            fsrs_card_json=_fsrs_future_card(days_ahead=5),
        )
    )
    await db.commit()

    plan = await build_daily_plan(db, student)
    review_tasks = [t for t in plan["tasks"] if t["type"] == "review"]
    assert len(review_tasks) == 0


@pytest.mark.asyncio
async def test_p1_no_fsrs_card_not_due(db, student):
    db.add(
        KCMastery(
            student_id=student,
            knowledge_point="GDMATH-TRI-01",
            p_mastery=0.7,
            p_init=0.45,
            p_transit=0.35,
            p_guess=0.25,
            p_slip=0.08,
            fsrs_card_json=None,
        )
    )
    await db.commit()

    plan = await build_daily_plan(db, student)
    review_tasks = [t for t in plan["tasks"] if t["type"] == "review"]
    assert len(review_tasks) == 0


# ── P3 tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_p3_weak_mastery_generates_weak_task(db, student):
    db.add(
        KCMastery(
            student_id=student,
            knowledge_point="GDMATH-SET-01",
            p_mastery=0.4,
            p_init=0.45,
            p_transit=0.35,
            p_guess=0.25,
            p_slip=0.08,
        )
    )
    await db.commit()

    plan = await build_daily_plan(db, student)
    weak_tasks = [t for t in plan["tasks"] if t["type"] == "weak_practice"]
    assert len(weak_tasks) == 1
    assert weak_tasks[0]["priority"] == 3
    assert "GDMATH-SET-01" in weak_tasks[0]["ku_ids"]


@pytest.mark.asyncio
async def test_p3_above_threshold_no_weak_task(db, student):
    db.add(
        KCMastery(
            student_id=student,
            knowledge_point="GDMATH-SET-01",
            p_mastery=0.75,
            p_init=0.45,
            p_transit=0.35,
            p_guess=0.25,
            p_slip=0.08,
        )
    )
    await db.commit()

    plan = await build_daily_plan(db, student)
    weak_tasks = [t for t in plan["tasks"] if t["type"] == "weak_practice"]
    assert len(weak_tasks) == 0


# ── P4 tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_p4_new_learn_no_prereqs(db, student, ku_seed):
    """New student with no kc_mastery: should recommend KUs with no prerequisites (ku_a, ku_c)."""
    plan = await build_daily_plan(db, student)
    new_tasks = [t for t in plan["tasks"] if t["type"] == "new_learn"]
    assert len(new_tasks) >= 1
    all_ku_ids = {ku_id for t in new_tasks for ku_id in t["ku_ids"]}
    assert ku_seed["ku_a"] in all_ku_ids
    assert ku_seed["ku_c"] in all_ku_ids
    # ku_b requires ku_a (not mastered), so should NOT appear
    assert ku_seed["ku_b"] not in all_ku_ids
    # ku_d requires ku_b (not mastered), should NOT appear
    assert ku_seed["ku_d"] not in all_ku_ids


@pytest.mark.asyncio
async def test_p4_prerequisite_unlocks_after_mastery(db, student, ku_seed):
    """After mastering ku_a, ku_b should be recommended."""
    ku_a = ku_seed["ku_a"]
    ku_b = ku_seed["ku_b"]

    db.add(
        KCMastery(
            student_id=student,
            knowledge_point=ku_a,
            p_mastery=0.8,
            p_init=0.3,
            p_transit=0.3,
            p_guess=0.15,
            p_slip=0.1,
        )
    )
    await db.commit()

    plan = await build_daily_plan(db, student)
    new_tasks = [t for t in plan["tasks"] if t["type"] == "new_learn"]
    all_ku_ids = {ku_id for t in new_tasks for ku_id in t["ku_ids"]}

    # ku_b's prerequisite (ku_a) is now mastered → should appear
    assert ku_b in all_ku_ids
    # ku_a itself already known → should NOT appear in new_learn
    assert ku_a not in all_ku_ids
    # ku_d still blocked (needs ku_b)
    assert ku_seed["ku_d"] not in all_ku_ids


@pytest.mark.asyncio
async def test_p4_chained_prerequisites(db, student, ku_seed):
    """Mastering ku_a and ku_b unlocks ku_d."""
    ku_a = ku_seed["ku_a"]
    ku_b = ku_seed["ku_b"]
    ku_d = ku_seed["ku_d"]

    for kp in [ku_a, ku_b]:
        db.add(
            KCMastery(
                student_id=student,
                knowledge_point=kp,
                p_mastery=0.9,
                p_init=0.3,
                p_transit=0.3,
                p_guess=0.15,
                p_slip=0.1,
            )
        )
    await db.commit()

    plan = await build_daily_plan(db, student)
    new_tasks = [t for t in plan["tasks"] if t["type"] == "new_learn"]
    all_ku_ids = {ku_id for t in new_tasks for ku_id in t["ku_ids"]}
    assert ku_d in all_ku_ids


@pytest.mark.asyncio
async def test_p4_below_mastery_threshold_does_not_unlock(db, student, ku_seed):
    """ku_a with p_mastery < 0.6 does NOT count as mastered → ku_b still blocked."""
    ku_a = ku_seed["ku_a"]
    ku_b = ku_seed["ku_b"]

    db.add(
        KCMastery(
            student_id=student,
            knowledge_point=ku_a,
            p_mastery=0.4,
            p_init=0.3,
            p_transit=0.3,
            p_guess=0.15,
            p_slip=0.1,
        )
    )
    await db.commit()

    plan = await build_daily_plan(db, student)
    new_tasks = [t for t in plan["tasks"] if t["type"] == "new_learn"]
    all_ku_ids = {ku_id for t in new_tasks for ku_id in t["ku_ids"]}
    assert ku_b not in all_ku_ids


@pytest.mark.asyncio
async def test_p4_verified_ku_preferred_over_unverified(db, student):
    """P4 verified 优先：有 verified 候选时，unverified（未过校验门的 LLM 产物）
    不进入新学路径。"""
    tb_id = f"test-tb-ver-{uuid.uuid4().hex[:6]}"
    c_id = f"test-c-ver-{uuid.uuid4().hex[:6]}"
    ku_v = f"test-ku-ver-{uuid.uuid4().hex[:6]}"
    ku_u = f"test-ku-unv-{uuid.uuid4().hex[:6]}"

    db.add(
        Textbook(
            id=tb_id,
            subject="math",
            grade="高一",
            edition="测试版",
            book_name="校验门测试教材",
        )
    )
    await db.flush()
    db.add(
        KnowledgeCluster(id=c_id, textbook_id=tb_id, name="校验章节", display_order=1)
    )
    await db.flush()
    for ku_id, verified in [(ku_v, True), (ku_u, False)]:
        db.add(
            KnowledgeUnit(
                id=ku_id,
                textbook_id=tb_id,
                cluster_id=c_id,
                name=f"KU-{ku_id[-6:]}",
                description="测试",
                prerequisites=[],
                related_kus=[],
                difficulty=0.3,
                exam_frequency="mid",
                question_types=["选择题"],
                ku_type="concept",
                mastery_levels=[],
                verified=verified,
            )
        )
    await db.commit()

    try:
        plan = await build_daily_plan(db, student, subject="math")
        new_tasks = [t for t in plan["tasks"] if t["type"] == "new_learn"]
        all_ku_ids = {ku_id for t in new_tasks for ku_id in t["ku_ids"]}
        assert ku_v in all_ku_ids
        assert ku_u not in all_ku_ids
    finally:
        await db.execute(
            delete(KnowledgeUnit).where(KnowledgeUnit.textbook_id == tb_id)
        )
        await db.execute(
            delete(KnowledgeCluster).where(KnowledgeCluster.textbook_id == tb_id)
        )
        await db.execute(delete(Textbook).where(Textbook.id == tb_id))
        await db.commit()


# ── 优先级顺序 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_priority_order_p1_before_p3(db, student):
    """P1 FSRS task must sort before P3 weak_practice task."""
    db.add(
        KCMastery(
            student_id=student,
            knowledge_point="GDMATH-SET-01",
            p_mastery=0.4,
            p_init=0.45,
            p_transit=0.35,
            p_guess=0.25,
            p_slip=0.08,
            fsrs_card_json=_fsrs_card(overdue_days=1),
        )
    )
    await db.commit()

    plan = await build_daily_plan(db, student)
    types_in_order = [t["type"] for t in plan["tasks"]]
    assert types_in_order.index("review") < types_in_order.index("weak_practice")


# ── 科目过滤 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subject_filter_isolates_correctly(db, student, ku_seed):
    """subject=math should return only math tasks (ku_seed is math)."""
    plan_math = await build_daily_plan(db, student, subject="math")

    # math plan should have P4 tasks (ku_seed is math)
    math_new = [t for t in plan_math["tasks"] if t["type"] == "new_learn"]
    assert len(math_new) >= 1
    # 隔离性：subject=math 过滤后所有任务都应属 math
    # （直接断言隔离属性，不依赖其它学科在共享 DB 里是否恰好为空）
    assert all(t["subject"] == "math" for t in plan_math["tasks"])


# ── API 端点测试 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_all_subjects(db, student, ku_seed):
    tok = _token(student)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(
            f"/v1/daily-plan/{student}", headers={"Authorization": f"Bearer {tok}"}
        )
    assert r.status_code == 200
    body = r.json()
    assert "tasks" in body
    assert "subjects_summary" in body
    assert "date" in body
    assert body["exam_countdown_days"] is None


@pytest.mark.asyncio
async def test_api_single_subject(db, student):
    tok = _token(student)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(
            f"/v1/daily-plan/{student}?subject=math",
            headers={"Authorization": f"Bearer {tok}"},
        )
    assert r.status_code == 200
    body = r.json()
    # all tasks should be math
    for t in body["tasks"]:
        assert t["subject"] == "math"


@pytest.mark.asyncio
async def test_api_requires_auth(student):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(f"/v1/daily-plan/{student}")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_api_empty_plan_for_new_student(db):
    """Student with zero data + 一个无任何内容的学科命名空间 → 空计划。
    用不存在内容的 subject（而非真实学科），保证在已灌库的共享 DB 上也确定为空。"""
    sid = uuid.uuid4()
    db.add(
        User(
            id=sid,
            phone=f"166{str(sid)[:8]}",
            role=UserRole.student,
            name="X",
            grade="高一",
        )
    )
    await db.commit()
    try:
        tok = _token(sid)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.get(
                f"/v1/daily-plan/{sid}?subject=__no_content__",
                headers={"Authorization": f"Bearer {tok}"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["tasks"] == []
    finally:
        await db.execute(delete(User).where(User.id == sid))
        await db.commit()


# ── subjects_summary 结构测试 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subjects_summary_structure(db, student, ku_seed):
    plan = await build_daily_plan(db, student)
    for s in plan["subjects_summary"]:
        assert "subject" in s
        assert "task_count" in s
        assert "estimated_minutes" in s
        assert s["task_count"] >= 0


@pytest.mark.asyncio
async def test_p1_estimated_minutes_per_ku(db, student):
    """2 due KUs → 2×5 = 10 estimated minutes."""
    for kp in ["GDMATH-SET-01", "GDMATH-SET-02"]:
        db.add(
            KCMastery(
                student_id=student,
                knowledge_point=kp,
                p_mastery=0.8,
                p_init=0.45,
                p_transit=0.35,
                p_guess=0.25,
                p_slip=0.08,
                fsrs_card_json=_fsrs_card(overdue_days=2),
            )
        )
    await db.commit()

    plan = await build_daily_plan(db, student)
    review_tasks = [t for t in plan["tasks"] if t["type"] == "review"]
    assert len(review_tasks) == 1
    assert review_tasks[0]["estimated_minutes"] == 10
    assert len(review_tasks[0]["ku_ids"]) == 2
