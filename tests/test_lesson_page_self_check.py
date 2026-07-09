"""
X.2 红线测试：同源自检（lesson_page 图示/答案/末步三处不一致 → 不交付）。
GET /v1/lesson/{question_id} 此前自检失败时仍会把内容原样返回给前端（只是不
落缓存+带个 self_check_passed=false 的flag），跟 CLAUDE.md 红线原文"三处不
一致不交付"不符——本次一并修复为真正拒绝交付(422)，而不只是补一条测试锁定
旧行为。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.main import app
from services.models import WrongQuestion, User, UserRole


@pytest.fixture(autouse=True)
def _auth(bypass_auth):
    """自访问正向测试统一绕过 IDOR 鉴权。"""


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
            phone=f"186{str(sid)[:8]}",
            role=UserRole.student,
            name="T-lesson-selfcheck",
            grade="高一",
        )
    )
    await db.commit()
    yield sid
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.fixture(scope="function")
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def _make_wrong_question(
    db: AsyncSession, student_id: uuid.UUID, *, question_text: str, correct_answer: str
) -> uuid.UUID:
    qid = uuid.uuid4()
    db.add(
        WrongQuestion(
            id=qid,
            student_id=student_id,
            subject="math",
            question_text=question_text,
            correct_answer=correct_answer,
            knowledge_points={},
        )
    )
    await db.commit()
    return qid


@pytest.mark.asyncio
async def test_self_check_failure_refuses_delivery(client, student, db):
    """内核对 x**2-4 的真实解是 zeros: [-2, 2]；故意存一个跟内核不一致的
    correct_answer，触发 generate_lesson_page 的 self_check_failed 分支，
    断言接口拒绝交付（422），而不是把内容原样吐出去只带一个flag。"""
    qid = await _make_wrong_question(
        db,
        student,
        question_text="x**2 - 4",
        correct_answer="这是一个跟内核完全对不上的错误答案",
    )
    try:
        resp = await client.get(f"/v1/lesson/{qid}")
        assert resp.status_code == 422
        assert "自检" in resp.json()["detail"]
        print("  同源自检失败 → 拒绝交付(422)，不再把内容原样吐出去 ✓")
    finally:
        await db.execute(delete(WrongQuestion).where(WrongQuestion.id == qid))
        await db.commit()


@pytest.mark.asyncio
async def test_self_check_pass_delivers_and_caches(client, student, db):
    """correct_answer 为空时 _answers_agree 恒真（无参照可比对），self_check
    应该通过，正常交付+落缓存——确认修复没有误伤正常路径。"""
    qid = await _make_wrong_question(
        db, student, question_text="x**2 - 4", correct_answer=""
    )
    try:
        resp = await client.get(f"/v1/lesson/{qid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["self_check_passed"] is True
        assert data["status"] == "ok"
        assert data["plot_data"]["steps"]

        # 第二次请求应该走缓存
        resp2 = await client.get(f"/v1/lesson/{qid}")
        assert resp2.status_code == 200
        assert resp2.json()["cached"] is True
        print("  同源自检通过 → 正常交付+落缓存，第二次命中缓存 ✓")
    finally:
        from services.models import LessonPage

        await db.execute(delete(LessonPage).where(LessonPage.question_id == qid))
        await db.execute(delete(WrongQuestion).where(WrongQuestion.id == qid))
        await db.commit()
