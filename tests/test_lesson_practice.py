"""
知识点讲解 & 专题练习接口测试
覆盖：
  - GET /v1/knowledge-points?student_id 带掌握度
  - GET /v1/knowledge-points/{ku_id}?student_id 带掌握度和前置KU掌握度
  - GET /v1/textbook-files/{file_id}/meta
  - POST /v1/practice/submit (答对/答错 隔离公共题库)
  - POST /v1/socratic/start-for-ku
"""
from __future__ import annotations

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sqlalchemy import select

from obase.config import settings
from obase.auth import create_access_token
from services.main import app
from services.models import (
    KnowledgeCluster, KnowledgeUnit, Textbook, TextbookFile,
    User, UserRole, WrongQuestion, InteractionEvent, KCMastery, MasterySnapshot, SocraticSession,
)


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
async def db():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(scope="function")
async def student(db: AsyncSession):
    sid = uuid.uuid4()
    db.add(User(id=sid, phone=f"155{str(sid.int)[:8]}", role=UserRole.student, name="练习生", grade="高一"))
    await db.commit()
    token = create_access_token({"sub": str(sid)})
    yield sid, token
    # teardown: FK 顺序
    await db.execute(delete(SocraticSession).where(SocraticSession.student_id == sid))
    await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id == sid))
    await db.execute(delete(MasterySnapshot).where(MasterySnapshot.student_id == sid))
    await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
    await db.execute(delete(InteractionEvent).where(InteractionEvent.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.fixture(scope="function")
async def seed_ku(db: AsyncSession):
    tb_id  = f"tb-lp-{uuid.uuid4().hex[:8]}"
    c_id   = f"cl-lp-{uuid.uuid4().hex[:8]}"
    ku1_id = f"ku-lp1-{uuid.uuid4().hex[:8]}"
    ku2_id = f"ku-lp2-{uuid.uuid4().hex[:8]}"

    db.add(Textbook(id=tb_id, subject="math", grade="高一", edition="测试版", book_name="练习教材"))
    await db.flush()
    db.add(KnowledgeCluster(id=c_id, textbook_id=tb_id, name="测试章节", display_order=1))
    await db.flush()
    db.add(KnowledgeUnit(
        id=ku1_id, textbook_id=tb_id, cluster_id=c_id,
        name="前置知识", description="先决条件",
        prerequisites=[], difficulty=0.3, exam_frequency="low", question_types=["选择题"],
        ku_type="concept", mastery_levels=[],
    ))
    db.add(KnowledgeUnit(
        id=ku2_id, textbook_id=tb_id, cluster_id=c_id,
        name="核心知识", description="核心内容",
        prerequisites=[ku1_id], difficulty=0.6, exam_frequency="high", question_types=["解答题"],
        ku_type="method", mastery_levels=[],
    ))
    # 平台 textbook_file
    file_id = f"tf-lp-{uuid.uuid4().hex[:8]}"
    db.add(TextbookFile(
        id=file_id, textbook_id=tb_id, filename="test.pdf",
        file_type="pdf", storage_path="curriculum_standards/test.pdf",
        has_text_layer=True,
    ))
    await db.commit()
    yield {"tb_id": tb_id, "c_id": c_id, "ku1_id": ku1_id, "ku2_id": ku2_id, "file_id": file_id}
    await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.textbook_id == tb_id))
    await db.execute(delete(KnowledgeCluster).where(KnowledgeCluster.textbook_id == tb_id))
    await db.execute(delete(TextbookFile).where(TextbookFile.textbook_id == tb_id))
    await db.execute(delete(Textbook).where(Textbook.id == tb_id))
    await db.commit()


@pytest.fixture(scope="function")
async def bank_question(db: AsyncSession, seed_ku):
    ku2_id = seed_ku["ku2_id"]
    qid = uuid.uuid4()
    db.add(WrongQuestion(
        id=qid,
        student_id=None,      # 公共题库
        subject="math",
        question_text="2+2=?",
        correct_answer="4",
        knowledge_points={ku2_id: "核心知识"},
        needs_image=False,
    ))
    await db.commit()
    yield qid
    await db.execute(delete(WrongQuestion).where(WrongQuestion.id == qid))
    await db.commit()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── tests: knowledge-points with mastery ──────────────────────────────────────

@pytest.mark.asyncio
async def test_list_knowledge_points_with_student_id(seed_ku, student):
    sid, token = student
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/knowledge-points",
                        params={"textbook_id": seed_ku["tb_id"], "student_id": str(sid)},
                        headers=_h(token))
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    # mastery_color present, defaults to 'unknown' (no interaction yet)
    for item in items:
        assert "p_mastery" in item
        assert "mastery_color" in item
        assert item["mastery_color"] == "unknown"


@pytest.mark.asyncio
async def test_list_knowledge_points_textbook_file_id(seed_ku, student):
    _, token = student
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/knowledge-points",
                        params={"textbook_id": seed_ku["tb_id"]},
                        headers=_h(token))
    assert r.status_code == 200
    items = r.json()
    assert all(item["textbook_file_id"] == seed_ku["file_id"] for item in items)


@pytest.mark.asyncio
async def test_get_single_ku_with_prereq_mastery(seed_ku, student):
    sid, token = student
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/v1/knowledge-points/{seed_ku['ku2_id']}",
                        params={"student_id": str(sid)},
                        headers=_h(token))
    assert r.status_code == 200
    d = r.json()
    assert d["textbook_file_id"] == seed_ku["file_id"]
    assert "prereq_mastery" in d
    # ku2 has ku1 as prereq
    assert any(p["ku_id"] == seed_ku["ku1_id"] for p in d["prereq_mastery"])


# ── tests: textbook file meta ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_textbook_file_meta(seed_ku, student):
    _, token = student
    fid = seed_ku["file_id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/v1/textbook-files/{fid}/meta", headers=_h(token))
    assert r.status_code == 200
    d = r.json()
    assert d["file_id"] == fid
    assert d["file_type"] == "pdf"
    assert d["has_text_layer"] is True


@pytest.mark.asyncio
async def test_get_textbook_file_meta_not_found(student):
    _, token = student
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/textbook-files/does-not-exist/meta", headers=_h(token))
    assert r.status_code == 404


# ── tests: practice/submit ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_practice_submit_correct_no_wrong_question_created(
    db, seed_ku, student, bank_question
):
    sid, token = student
    ku2_id = seed_ku["ku2_id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/practice/submit", json={
            "question_id": str(bank_question),
            "student_id": str(sid),
            "student_answer": "4",
            "is_correct": True,
            "ku_id": ku2_id,
        })
    assert r.status_code == 200
    d = r.json()
    assert d["is_correct"] is True
    assert d["wrong_question_id"] is None
    # 公共题库题目不受影响（student_id 仍为 NULL）
    bq = (await db.execute(
        select(WrongQuestion).where(WrongQuestion.id == bank_question)
    )).scalar_one_or_none()
    assert bq is not None
    assert bq.student_id is None


@pytest.mark.asyncio
async def test_practice_submit_wrong_creates_student_record_not_bank(
    db, seed_ku, student, bank_question
):
    sid, token = student
    ku2_id = seed_ku["ku2_id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/practice/submit", json={
            "question_id": str(bank_question),
            "student_id": str(sid),
            "student_answer": "5",
            "is_correct": False,
            "ku_id": ku2_id,
        })
    assert r.status_code == 200
    d = r.json()
    assert d["is_correct"] is False
    assert d["wrong_question_id"] is not None

    # 验证：学生错题记录确实写入，且 student_id = sid
    student_wq = (await db.execute(
        select(WrongQuestion).where(WrongQuestion.id == uuid.UUID(d["wrong_question_id"]))
    )).scalar_one_or_none()
    assert student_wq is not None
    assert str(student_wq.student_id) == str(sid)
    assert student_wq.student_answer == "5"
    assert student_wq.correct_answer == "4"

    # 公共题库行 student_id 仍为 NULL
    bq = (await db.execute(
        select(WrongQuestion).where(WrongQuestion.id == bank_question)
    )).scalar_one_or_none()
    assert bq.student_id is None

    # cleanup
    await db.execute(delete(WrongQuestion).where(WrongQuestion.id == student_wq.id))
    await db.commit()


@pytest.mark.asyncio
async def test_practice_submit_bank_question_not_found(student):
    sid, _ = student
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/practice/submit", json={
            "question_id": str(uuid.uuid4()),
            "student_id": str(sid),
            "student_answer": "x",
            "is_correct": False,
            "ku_id": "fake-ku",
        })
    assert r.status_code == 404


# ── tests: socratic/start-for-ku ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_socratic_start_for_ku_creates_session(db, seed_ku, student):
    sid, _ = student
    ku2_id = seed_ku["ku2_id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/socratic/start-for-ku", json={
            "ku_id": ku2_id,
            "student_id": str(sid),
        })
    assert r.status_code == 200
    d = r.json()
    assert "session_id" in d
    assert "first_question" in d
    assert len(d["first_question"]) > 0

    # cleanup
    from services.models import SocraticSession
    wq_cleanup = (await db.execute(
        select(WrongQuestion)
        .where(WrongQuestion.student_id == sid, WrongQuestion.question_text.like(f"%{ku2_id[:10]}%"))
    )).scalars().all()
    for wq in wq_cleanup:
        await db.execute(delete(WrongQuestion).where(WrongQuestion.id == wq.id))
    await db.commit()
