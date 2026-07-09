"""
error-journal subject 过滤 + subject 字段回传（daily-plan 任务点击死链修复的后端半边）。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.main import app
from services.models import User, UserRole, WrongQuestion


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
async def student(db):
    sid = uuid.uuid4()
    db.add(
        User(
            id=sid,
            phone=f"185{str(sid)[:8]}",
            role=UserRole.student,
            name="Test3",
            grade="高二",
        )
    )
    await db.commit()
    yield sid
    await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.fixture(scope="function")
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture(scope="function")
async def mixed_subject_wrong_questions(db, student):
    """同一学生名下math+physics各一道错题，用于验证subject过滤不会把两科混在一起。"""
    math_id, physics_id = uuid.uuid4(), uuid.uuid4()
    db.add(
        WrongQuestion(
            id=math_id,
            student_id=student,
            paper_id=None,
            question_text="解方程 x^2 = 4",
            correct_answer="x=2 或 x=-2",
            knowledge_points={"GDMATH-CONIC-01": 1.0},
            subject="math",
        )
    )
    db.add(
        WrongQuestion(
            id=physics_id,
            student_id=student,
            paper_id=None,
            question_text="小车受力分析",
            correct_answer="F=ma",
            knowledge_points={"PHYS-FORCE-01": 1.0},
            subject="physics",
        )
    )
    await db.commit()
    return {"math": math_id, "physics": physics_id}


@pytest.mark.asyncio
async def test_error_journal_subject_filter(
    client, student, mixed_subject_wrong_questions
):
    """
    subject 过滤 + 无过滤两种情形放同一个 test 里（而非分两个 test function）：
    get_pg_pool() 是进程级缓存的原生 asyncpg 连接池，绑定创建它时所在的 event loop；
    pytest-asyncio 默认每个 test function 一个新 loop，两个 test 各自触发
    get_error_distribution() 会导致池跨 loop 复用而报
    'cannot perform operation: another operation is in progress'——这是测试基建的
    既有缺陷（本次改动之前这个端点完全没有测试覆盖过），不是本次 subject 过滤改动
    引入的问题，不在本次修复范围内，这里只是绕开它。
    """
    resp_math = await client.get(
        f"/v1/error-journal/{student}", params={"subject": "math"}
    )
    assert resp_math.status_code == 200
    items_math = resp_math.json()["items"]
    assert len(items_math) == 1
    assert items_math[0]["subject"] == "math"
    assert items_math[0]["question_id"] == str(mixed_subject_wrong_questions["math"])

    resp_physics = await client.get(
        f"/v1/error-journal/{student}", params={"subject": "physics"}
    )
    assert resp_physics.status_code == 200
    items_physics = resp_physics.json()["items"]
    assert len(items_physics) == 1
    assert items_physics[0]["subject"] == "physics"

    resp_all = await client.get(f"/v1/error-journal/{student}")
    assert resp_all.status_code == 200
    items_all = resp_all.json()["items"]
    assert len(items_all) == 2
    assert {it["subject"] for it in items_all} == {"math", "physics"}

    print("  GET /v1/error-journal?subject=X — 按学科过滤，不再混在一起 ✓")
    print(
        "  GET /v1/error-journal（无 subject）— 返回全部，每条都带正确的 subject 字段 ✓"
    )
