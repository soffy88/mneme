"""
B.3 DoD 测试：认知状态 API 路由
=================================
覆盖：
  POST /v1/interaction
  GET  /v1/mastery/{student_id}
  GET  /v1/mastery/curve/{student_id}/{ku_id}
  GET  /v1/review-queue/{student_id}
  GET  /v1/ku
  GET  /v1/ku/{ku_id}
DoD：接口返回正确契约；重启状态不丢（通过 DB 验证）。
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.main import app
from services.models import InteractionEvent, KCMastery, MasterySnapshot, User, UserRole

KC_ID = "GDMATH-CONIC-01"


@pytest.fixture(autouse=True)
def _auth(bypass_auth):
    """本文件全为自访问正向测试：统一绕过 IDOR 鉴权。"""



# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
async def db():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(scope="function")
async def student(db):
    sid = uuid.uuid4()
    db.add(User(id=sid, phone=f"180{str(sid)[:8]}", role=UserRole.student))
    await db.commit()
    yield sid
    await db.execute(delete(MasterySnapshot).where(MasterySnapshot.student_id == sid))
    await db.execute(delete(InteractionEvent).where(InteractionEvent.student_id == sid))
    await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.fixture(scope="function")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── POST /v1/interaction ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_interaction_returns_findings(client, student):
    resp = await client.post("/v1/interaction", json={
        "student_id": str(student),
        "ku_id": KC_ID,
        "is_correct": False,
        "struggled": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ku_id"] == KC_ID
    assert "p_mastery" in data
    assert "error_type" in data
    assert "rating" in data
    assert data["error_type"] in ("careless", "dontknow")
    print(f"  POST /v1/interaction → p_mastery={data['p_mastery']}, error={data['error_type']} ✓")


@pytest.mark.asyncio
async def test_interaction_state_persists(client, student, db):
    """答题后 kc_mastery 写库，状态不丢。"""
    await client.post("/v1/interaction", json={
        "student_id": str(student), "ku_id": KC_ID, "is_correct": True,
    })
    row = (await db.execute(
        __import__("sqlalchemy", fromlist=["select"]).select(KCMastery)
        .where(KCMastery.student_id == student)
        .where(KCMastery.knowledge_point == KC_ID)
    )).scalar_one_or_none()
    assert row is not None, "kc_mastery 应落库，重启后状态不丢"
    print(f"  状态持久化验证: p_mastery={row.p_mastery:.4f} ✓")


# ── GET /v1/mastery/{student_id} ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mastery_overview_sorted(client, student):
    for kc in (KC_ID, "GDMATH-SET-01"):
        await client.post("/v1/interaction", json={
            "student_id": str(student), "ku_id": kc, "is_correct": True,
        })
    resp = await client.get(f"/v1/mastery/{student}")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 2
    vals = [it["effective_mastery"] for it in items]
    assert vals == sorted(vals), "掌握度应升序"
    assert all("peer_percentile" in it for it in items), "每项应含 peer_percentile"
    print("  GET /v1/mastery 升序+百分位 ✓")


# ── GET /v1/mastery/curve/{student_id}/{ku_id} ───────────────────────────────

@pytest.mark.asyncio
async def test_mastery_curve_empty_then_filled(client, student):
    resp = await client.get(f"/v1/mastery/curve/{student}/{KC_ID}")
    assert resp.status_code == 200
    assert resp.json()["points"] == [], "无数据时 points 应为空"

    await client.post("/v1/interaction", json={
        "student_id": str(student), "ku_id": KC_ID, "is_correct": True,
    })
    resp = await client.get(f"/v1/mastery/curve/{student}/{KC_ID}")
    assert resp.status_code == 200
    curve = resp.json()["points"]   # 当前契约：{ku_id, ku_name, points:[...]}
    assert len(curve) == 1
    assert "month" in curve[0]
    assert "mastery" in curve[0]
    assert "dominant_error_type" in curve[0]
    print(f"  GET /v1/mastery/curve → {curve[0]['month']} ✓")


@pytest.mark.asyncio
async def test_mastery_curve_no_conflict_with_overview(client, student):
    """确认 /mastery/curve/... 路由不被 /mastery/{student_id} 吞掉。"""
    resp = await client.get(f"/v1/mastery/curve/{student}/{KC_ID}")
    assert resp.status_code == 200
    body = resp.json()
    # 当前契约：curve 返回 {ku_id, ku_name, points:[...]}，非掌握度 overview 列表
    assert isinstance(body, dict) and "points" in body and body["ku_id"] == KC_ID
    print("  curve 路由优先级正确，未被 {student_id} 路由拦截 ✓")


# ── GET /v1/review-queue/{student_id} ────────────────────────────────────────

@pytest.mark.asyncio
async def test_review_queue_after_wrong(client, student):
    await client.post("/v1/interaction", json={
        "student_id": str(student), "ku_id": KC_ID, "is_correct": False,
    })
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    resp = await client.get(f"/v1/review-queue/{student}", params={"now": future})
    assert resp.status_code == 200
    queue = resp.json()
    assert len(queue) >= 1
    assert queue[0]["ku_id"] == KC_ID
    assert "due" in queue[0]
    print(f"  GET /v1/review-queue → {len(queue)} 条待复习 ✓")


# ── GET /v1/ku ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_kc_list(client):
    resp = await client.get("/v1/ku")
    assert resp.status_code == 200
    kc_list = resp.json()
    assert len(kc_list) == 29, f"应有 29 个 KC，实际 {len(kc_list)}"
    assert all("ku_id" in kc for kc in kc_list)
    print(f"  GET /v1/ku → {len(kc_list)} 个知识点 ✓")


@pytest.mark.asyncio
async def test_kc_detail(client):
    resp = await client.get(f"/v1/ku/{KC_ID}")
    assert resp.status_code == 200
    assert resp.json()["ku_id"] == KC_ID
    print(f"  GET /v1/ku/{KC_ID} ✓")


@pytest.mark.asyncio
async def test_kc_detail_not_found(client):
    resp = await client.get("/v1/ku/NOT-EXIST-KC")
    assert resp.status_code == 404
    print("  GET /v1/ku/NOT-EXIST-KC → 404 ✓")
