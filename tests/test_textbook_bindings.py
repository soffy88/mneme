"""
N.4 用户教材绑定：textbook_bindings 读写 + 接入 build_daily_plan 的 P4 新知识点推荐。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.daily_plan_service import build_daily_plan
from services.main import app
from services.models import KnowledgeCluster, KnowledgeUnit, Textbook, User, UserRole


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
            phone=f"187{str(sid)[:8]}",
            role=UserRole.student,
            name="Test5",
            grade="高二",
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


@pytest.fixture(scope="function")
async def two_math_textbooks(db):
    """两本数学教材，各配一个新知识点（无前置），供"绑定后只从那本教材推荐"测试用。"""
    ids = {}
    for label in ("a", "b"):
        tb_id = f"test-tb-{label}-{uuid.uuid4().hex[:8]}"
        cluster_id = f"test-cl-{label}-{uuid.uuid4().hex[:8]}"
        ku_id = f"test-ku-{label}-{uuid.uuid4().hex[:8]}"
        db.add(
            Textbook(
                id=tb_id,
                subject="math",
                grade="高二",
                edition="测试版",
                book_name=f"测试数学教材{label}",
            )
        )
        await db.flush()
        db.add(
            KnowledgeCluster(
                id=cluster_id, textbook_id=tb_id, name="第一章", display_order=1
            )
        )
        await db.flush()
        db.add(
            KnowledgeUnit(
                id=ku_id,
                textbook_id=tb_id,
                cluster_id=cluster_id,
                name=f"测试新知识点{label}",
                description="测试用",
                difficulty=0.5,
                prerequisites=[],
                verified=True,
            )
        )
        ids[label] = {"textbook_id": tb_id, "cluster_id": cluster_id, "ku_id": ku_id}
    await db.commit()
    try:
        yield ids
    finally:
        for v in ids.values():
            await db.execute(
                delete(KnowledgeUnit).where(KnowledgeUnit.id == v["ku_id"])
            )
            await db.execute(
                delete(KnowledgeCluster).where(KnowledgeCluster.id == v["cluster_id"])
            )
            await db.execute(delete(Textbook).where(Textbook.id == v["textbook_id"]))
        await db.commit()


@pytest.mark.asyncio
async def test_textbook_bindings_crud(client, student, two_math_textbooks):
    """默认空 → 部分更新 → 非法学科/教材/学科不匹配拒绝 → null 清空该学科绑定。"""
    tb_a = two_math_textbooks["a"]["textbook_id"]
    tb_b = two_math_textbooks["b"]["textbook_id"]

    resp = await client.get(f"/v1/users/{student}/textbook-bindings")
    assert resp.status_code == 200
    assert resp.json() == {}

    resp = await client.post(
        f"/v1/users/{student}/textbook-bindings", json={"math": tb_a}
    )
    assert resp.status_code == 200
    assert resp.json() == {"math": tb_a}

    # 换绑到另一本
    resp = await client.post(
        f"/v1/users/{student}/textbook-bindings", json={"math": tb_b}
    )
    assert resp.status_code == 200
    assert resp.json() == {"math": tb_b}

    # 未知学科(history)拒绝——Pydantic TextbookBindingsReq 没有这个字段，请求体
    # 层面就会被丢弃过滤掉，测不出服务层的 _ALLOWED_SUBJECTS 校验，这条覆盖在
    # test_unknown_subject_rejected_at_service_layer 里直接测服务函数。

    # 教材不存在拒绝
    resp = await client.post(
        f"/v1/users/{student}/textbook-bindings", json={"physics": "NOT-EXIST-TB"}
    )
    assert resp.status_code == 422

    # 教材学科不匹配拒绝（tb_a 是 math，绑给 physics）
    resp = await client.post(
        f"/v1/users/{student}/textbook-bindings", json={"physics": tb_a}
    )
    assert resp.status_code == 422

    # null 清空该学科绑定
    resp = await client.post(
        f"/v1/users/{student}/textbook-bindings", json={"math": None}
    )
    assert resp.status_code == 200
    assert resp.json() == {}
    print("  textbook-bindings CRUD + 非法值拒绝 + null 清空语义 ✓")


@pytest.mark.asyncio
async def test_unknown_subject_rejected_at_service_layer(student, db):
    from services.textbook_bindings_service import set_textbook_bindings

    result = await set_textbook_bindings(db, student, {"history": "x"})
    assert "error" in result
    print("  set_textbook_bindings 服务层未知学科拒绝 ✓")


@pytest.mark.asyncio
async def test_list_textbooks_by_subject(client, two_math_textbooks):
    resp = await client.get("/v1/textbooks", params={"subject": "math"})
    assert resp.status_code == 200
    ids = {b["textbook_id"] for b in resp.json()}
    assert two_math_textbooks["a"]["textbook_id"] in ids
    assert two_math_textbooks["b"]["textbook_id"] in ids
    print("  GET /v1/textbooks?subject=math 列出可选教材 ✓")


@pytest.mark.asyncio
async def test_bound_textbook_scopes_p4_new_learn(
    client, student, two_math_textbooks, db
):
    """绑定数学教材A后，P4 新知识点推荐只应包含教材A的知识点，不含教材B（也不含库里
    其它未绑定教材的真实数学KU——同一批 fixture 里没建，天然验证不到，但过滤逻辑
    对教材B成立就足够证明"按 textbook_id 精确匹配"生效，不是碰巧漏网）。"""
    ku_a = two_math_textbooks["a"]["ku_id"]
    ku_b = two_math_textbooks["b"]["ku_id"]
    tb_a = two_math_textbooks["a"]["textbook_id"]

    resp = await client.post(
        f"/v1/users/{student}/textbook-bindings", json={"math": tb_a}
    )
    assert resp.status_code == 200

    now = datetime.now(timezone.utc)
    plan = await build_daily_plan(db, student, subject="math", now=now)
    new_learn_ku_ids: set[str] = set()
    for t in plan["tasks"]:
        if t["type"] == "new_learn":
            new_learn_ku_ids.update(t["ku_ids"])

    assert ku_a in new_learn_ku_ids
    assert ku_b not in new_learn_ku_ids
    print("  绑定教材A后 P4 新知识点推荐只含教材A的KU，教材B被过滤掉 ✓")


@pytest.mark.asyncio
async def test_unbound_subject_keeps_existing_mixed_behavior(
    student, two_math_textbooks, db
):
    """未绑定数学教材时，P4 新知识点推荐应该两本教材的知识点都可能出现（向后兼容，
    行为不变）。"""
    ku_a = two_math_textbooks["a"]["ku_id"]
    ku_b = two_math_textbooks["b"]["ku_id"]

    now = datetime.now(timezone.utc)
    plan = await build_daily_plan(db, student, subject="math", now=now)
    new_learn_ku_ids: set[str] = set()
    for t in plan["tasks"]:
        if t["type"] == "new_learn":
            new_learn_ku_ids.update(t["ku_ids"])

    assert ku_a in new_learn_ku_ids
    assert ku_b in new_learn_ku_ids
    print("  未绑定教材时 P4 新知识点推荐两本教材都在池子里，行为不变 ✓")
