"""
软前置(soft_prerequisites)测试——建议先学但不阻断，跟 prerequisites(硬前置，驱动
P4 新知识点解锁/fringe 门控)语义独立。灵感来自审计 os-taxonomy 数据集时发现的
hard/soft 前置边建模思路，但不导入任何外部数据，纯粹是 Mneme 自己 schema 的独立
小增强。覆盖：新字段默认空、两个 KU 详情/列表接口正确返回、不影响 P4 硬门控行为。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from obase.auth import create_access_token
from services.daily_plan_service import build_daily_plan
from services.main import app
from services.models import KnowledgeCluster, KnowledgeUnit, Textbook, User, UserRole


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
            phone=f"189{str(sid)[:8]}",
            role=UserRole.student,
            name="T-soft-prereq",
            grade="高一",
        )
    )
    await db.commit()
    yield sid
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.fixture(scope="function")
async def seed(db: AsyncSession):
    """一本教材 + 2 个 KU：ku_target 硬前置=[]、软前置=[ku_soft_prereq]（未掌握），
    验证软前置既能正确读写，又不会像硬前置一样阻断 P4 新知识点解锁。"""
    tb_id = f"test-tb-{uuid.uuid4().hex[:8]}"
    c_id = f"test-c-{uuid.uuid4().hex[:8]}"
    ku_soft_id = f"test-ku-soft-{uuid.uuid4().hex[:8]}"
    ku_target_id = f"test-ku-target-{uuid.uuid4().hex[:8]}"

    db.add(
        Textbook(
            id=tb_id,
            subject="math",
            grade="高一",
            edition="测试版",
            book_name="测试教材",
        )
    )
    await db.flush()
    db.add(KnowledgeCluster(id=c_id, textbook_id=tb_id, name="第一章", display_order=1))
    await db.flush()
    db.add(
        KnowledgeUnit(
            id=ku_soft_id,
            textbook_id=tb_id,
            cluster_id=c_id,
            name="建议先学的知识点",
            description="",
            prerequisites=[],
            difficulty=0.3,
            verified=True,
        )
    )
    db.add(
        KnowledgeUnit(
            id=ku_target_id,
            textbook_id=tb_id,
            cluster_id=c_id,
            name="目标知识点",
            description="",
            prerequisites=[],  # 硬前置为空——不应被任何软前置未掌握而挡住
            soft_prerequisites=[ku_soft_id],
            difficulty=0.5,
            verified=True,
        )
    )
    await db.commit()
    try:
        yield {"tb_id": tb_id, "ku_soft_id": ku_soft_id, "ku_target_id": ku_target_id}
    finally:
        await db.execute(
            delete(KnowledgeUnit).where(KnowledgeUnit.textbook_id == tb_id)
        )
        await db.execute(
            delete(KnowledgeCluster).where(KnowledgeCluster.textbook_id == tb_id)
        )
        await db.execute(delete(Textbook).where(Textbook.id == tb_id))
        await db.commit()


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_soft_prerequisites_default_empty_and_roundtrips(seed, student):
    token = create_access_token({"sub": str(student)})
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        # 列表接口
        r = await c.get(
            "/v1/knowledge-points",
            params={"textbook_id": seed["tb_id"]},
            headers=_headers(token),
        )
        assert r.status_code == 200
        by_id = {item["id"]: item for item in r.json()}
        assert by_id[seed["ku_soft_id"]]["soft_prerequisites"] == []
        assert by_id[seed["ku_target_id"]]["soft_prerequisites"] == [seed["ku_soft_id"]]

        # 详情接口
        r = await c.get(
            f"/v1/knowledge-points/{seed['ku_target_id']}", headers=_headers(token)
        )
        assert r.status_code == 200
        assert r.json()["soft_prerequisites"] == [seed["ku_soft_id"]]
    print("  soft_prerequisites 列表/详情接口读写正确，默认空表 ✓")


@pytest.mark.asyncio
async def test_soft_prerequisites_do_not_block_p4_new_learn(seed, student, db):
    """核心验证：ku_target 的软前置(ku_soft_id)完全未掌握，但硬前置(prerequisites)
    为空——P4 新知识点推荐应该正常把 ku_target 纳入候选，不能被软前置卡住。这是
    软/硬前置语义独立的关键：软前置只是建议，不是门控。"""
    now = datetime.now(timezone.utc)
    plan = await build_daily_plan(db, student, subject="math", now=now)
    new_learn_ku_ids: set[str] = set()
    for t in plan["tasks"]:
        if t["type"] == "new_learn":
            new_learn_ku_ids.update(t["ku_ids"])
    assert seed["ku_target_id"] in new_learn_ku_ids
    print("  软前置未掌握不阻断 P4 新知识点解锁（跟硬前置语义独立）✓")
