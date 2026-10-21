"""缺口单点练闭环 MCP 层：授权（学生默认集）+ 逐题 SubmitAnswer 回写 + 防重放。

真实 HTTP，打测试库 mneme_test（运行方式同 scripts/check.sh 的 DATABASE_URL 覆盖）。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.auth import create_access_token
from obase.config import settings
from services import prereq_diagnosis_service as pds
from services.main import app
from services.models import KCMastery, User, UserRole
from services.tool_grants import DEFAULT_STUDENT_TOOLS, GAP_DRILL_TOOLS

from .db_test_helpers import cleanup_test_student


def _h(user_id: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}


@pytest.fixture(scope="function")
async def db():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(scope="function")
async def actors(db, monkeypatch):
    admin_id, stu, par = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("ADMIN_USER_IDS", str(admin_id))
    db.add(User(id=admin_id, role=UserRole.student, name="管理员"))
    db.add(User(id=stu, role=UserRole.student, name="单练学生"))
    db.add(User(id=par, role=UserRole.parent, name="家长"))
    await db.commit()
    yield {"admin": admin_id, "stu": stu, "par": par}
    await db.rollback()
    for sid in (stu, admin_id, par):
        await db.execute(text("DELETE FROM agent.audit_log WHERE student_id = :s"), {"s": sid})
        await db.execute(text("DELETE FROM gate.pending_question WHERE student_id = :s"), {"s": sid})
        await db.execute(text("DELETE FROM agent.user_grants WHERE student_id = :s"), {"s": sid})
        await db.commit()
        await cleanup_test_student(db, sid)


@pytest.fixture(scope="function")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


_ROOTS = [{"ku_id": "cnmath:cnm_p001", "pending_prereqs": ["cnmath:cnm_p001"]}]


def test_gap_drill_tools_in_student_defaults():
    assert GAP_DRILL_TOOLS <= DEFAULT_STUDENT_TOOLS


@pytest.mark.asyncio
async def test_parent_cannot_start_gap_drill(actors, client):
    r = await client.post(
        "/mcp/StartGapDrill", json={"weak_roots": _ROOTS}, headers=_h(actors["par"])
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_student_drill_bank_answer_writes_mastery(actors, client, db):
    stu = actors["stu"]
    r = await client.post(
        "/mcp/StartGapDrill",
        json={"weak_roots": _ROOTS, "count": 5, "original_ku_id": "cnmath:cnm_p002"},
        headers=_h(stu),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    first_q = body["next"]["question"]
    assert "answer" not in first_q
    session = body["session"]

    ans = str(pds.question_by_id(first_q["id"])["answer"])
    r2 = await client.post(
        "/mcp/SubmitGapDrillAnswer",
        json={"session": session, "answer": ans},
        headers=_h(stu),
    )
    assert r2.status_code == 200, r2.text
    wb = r2.json()["mastery_writeback"]
    assert wb["written"] is True and wb["is_correct"] is True
    assert wb["kc_id"] == "cnmath:cnm_p001"

    db.expire_all()
    row = (
        await db.execute(
            select(KCMastery).where(
                KCMastery.student_id == stu,
                KCMastery.knowledge_point == "cnmath:cnm_p001",
            )
        )
    ).scalars().first()
    assert row is not None and 0 < (row.p_mastery or 0) <= 0.97

    # 重放同一步：不重复写
    r3 = await client.post(
        "/mcp/SubmitGapDrillAnswer",
        json={"session": session, "answer": ans},
        headers=_h(stu),
    )
    assert r3.json()["mastery_writeback"]["written"] is False
    assert r3.json()["mastery_writeback"]["reason"] == "duplicate"


@pytest.mark.asyncio
async def test_self_assessed_answer_never_writes(actors, client, db):
    stu = actors["stu"]
    r = await client.post(
        "/mcp/StartGapDrill", json={"weak_roots": _ROOTS, "count": 5}, headers=_h(stu)
    )
    session = r.json()["session"]
    r2 = await client.post(
        "/mcp/SubmitGapDrillAnswer",
        json={"session": session, "result": "skip"},
        headers=_h(stu),
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["mastery_writeback"] == {"written": False, "reason": "self_assessed"}
