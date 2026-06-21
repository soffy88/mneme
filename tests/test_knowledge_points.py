"""
知识单元接口测试 — Epic N 阶段1.5
覆盖：GET /v1/knowledge-points?subject= 列表查询、单条查询、新字段正确返回
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from obase.auth import create_access_token
from services.main import app
from services.models import (
    KnowledgeCluster, KnowledgeUnit, Textbook, User, UserRole,
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
async def seed(db: AsyncSession):
    """Insert a mini 教材 + 2 clusters + 3 KUs; tear down after each test."""
    tb_id  = f"test-tb-{uuid.uuid4().hex[:8]}"
    c1_id  = f"test-c1-{uuid.uuid4().hex[:8]}"
    c2_id  = f"test-c2-{uuid.uuid4().hex[:8]}"
    ku1_id = f"test-ku1-{uuid.uuid4().hex[:8]}"
    ku2_id = f"test-ku2-{uuid.uuid4().hex[:8]}"
    ku3_id = f"test-ku3-{uuid.uuid4().hex[:8]}"

    db.add(Textbook(id=tb_id, subject="math", grade="高一", edition="测试版",
                    book_name="测试数学必修"))
    await db.flush()

    db.add(KnowledgeCluster(id=c1_id, textbook_id=tb_id, name="第一章", display_order=1))
    db.add(KnowledgeCluster(id=c2_id, textbook_id=tb_id, name="第二章", display_order=2))
    await db.flush()

    db.add(KnowledgeUnit(
        id=ku1_id, textbook_id=tb_id, cluster_id=c1_id,
        name="集合概念", description="集合入门",
        prerequisites=[], related_kus=[ku2_id],
        difficulty=0.3, exam_frequency="mid",
        question_types=["选择题"], ku_type="concept",
        curriculum_standard="B4.1", mastery_levels=[{"level": 1, "label": "认识"}],
    ))
    db.add(KnowledgeUnit(
        id=ku2_id, textbook_id=tb_id, cluster_id=c1_id,
        name="集合运算", description="交并补",
        prerequisites=[ku1_id], related_kus=[],
        difficulty=0.5, exam_frequency="high",
        question_types=["选择题", "解答题"], ku_type="method",
        curriculum_standard="B4.2", mastery_levels=[],
    ))
    db.add(KnowledgeUnit(
        id=ku3_id, textbook_id=tb_id, cluster_id=c2_id,
        name="函数概念", description="映射与函数",
        prerequisites=[], related_kus=[],
        difficulty=0.4, exam_frequency="high",
        question_types=["解答题"], ku_type="concept",
        curriculum_standard=None, mastery_levels=[],
    ))
    await db.commit()

    yield {"tb_id": tb_id, "c1_id": c1_id, "c2_id": c2_id,
           "ku1_id": ku1_id, "ku2_id": ku2_id, "ku3_id": ku3_id}

    # teardown: 先删 units → clusters → textbook（FK 顺序）
    await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.textbook_id == tb_id))
    await db.execute(delete(KnowledgeCluster).where(KnowledgeCluster.textbook_id == tb_id))
    await db.execute(delete(Textbook).where(Textbook.id == tb_id))
    await db.commit()


async def _make_student(db: AsyncSession) -> uuid.UUID:
    sid = uuid.uuid4()
    db.add(User(id=sid, phone=f"188{str(sid)[:8]}", role=UserRole.student, name="T", grade="高一"))
    await db.commit()
    return sid


@pytest.fixture(scope="function")
async def student(db: AsyncSession):
    sid = await _make_student(db)
    yield create_access_token({"sub": str(sid)})
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


# ── helpers ───────────────────────────────────────────────────────────────────

def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_by_subject_returns_seeded_kus(seed, student):
    tb_id = seed["tb_id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/knowledge-points", params={"subject": "math"},
                        headers=_headers(student))
    assert r.status_code == 200
    data = r.json()
    # 可能已有其他 math KU（sample data），只需我们 seeded 的 3 个都在
    ids = {item["id"] for item in data}
    assert seed["ku1_id"] in ids
    assert seed["ku2_id"] in ids
    assert seed["ku3_id"] in ids


@pytest.mark.asyncio
async def test_list_by_textbook_id_isolates_correctly(seed, student):
    tb_id = seed["tb_id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/knowledge-points", params={"textbook_id": tb_id},
                        headers=_headers(student))
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3
    names = {d["name"] for d in data}
    assert {"集合概念", "集合运算", "函数概念"} == names


@pytest.mark.asyncio
async def test_list_by_cluster_id(seed, student):
    c1_id = seed["c1_id"]
    tb_id = seed["tb_id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/knowledge-points",
                        params={"textbook_id": tb_id, "cluster_id": c1_id},
                        headers=_headers(student))
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert all(d["cluster_id"] == c1_id for d in data)


@pytest.mark.asyncio
async def test_new_fields_present_in_list(seed, student):
    tb_id = seed["tb_id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/knowledge-points", params={"textbook_id": tb_id},
                        headers=_headers(student))
    data = r.json()
    ku1 = next(d for d in data if d["name"] == "集合概念")
    assert ku1["difficulty"] == pytest.approx(0.3, abs=1e-4)
    assert ku1["exam_frequency"] == "mid"
    assert ku1["ku_type"] == "concept"
    assert ku1["question_types"] == ["选择题"]
    assert ku1["curriculum_standard"] == "B4.1"
    assert isinstance(ku1["prerequisites"], list)
    assert isinstance(ku1["mastery_levels"], list)
    assert len(ku1["mastery_levels"]) == 1


@pytest.mark.asyncio
async def test_prerequisites_roundtrip(seed, student):
    tb_id  = seed["tb_id"]
    ku1_id = seed["ku1_id"]
    ku2_id = seed["ku2_id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/knowledge-points", params={"textbook_id": tb_id},
                        headers=_headers(student))
    ku2 = next(d for d in r.json() if d["id"] == ku2_id)
    assert ku2["prerequisites"] == [ku1_id]


@pytest.mark.asyncio
async def test_get_single_ku(seed, student):
    ku1_id = seed["ku1_id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/v1/knowledge-points/{ku1_id}", headers=_headers(student))
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == ku1_id
    assert d["name"] == "集合概念"
    assert d["difficulty"] == pytest.approx(0.3, abs=1e-4)


@pytest.mark.asyncio
async def test_get_single_ku_not_found(student):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/knowledge-points/does-not-exist", headers=_headers(student))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_curriculum_standard_can_be_null(seed, student):
    ku3_id = seed["ku3_id"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/v1/knowledge-points/{ku3_id}", headers=_headers(student))
    assert r.status_code == 200
    assert r.json()["curriculum_standard"] is None


@pytest.mark.asyncio
async def test_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/knowledge-points")
    assert r.status_code == 401
