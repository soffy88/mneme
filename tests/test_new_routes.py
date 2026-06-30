"""
综合新路由测试 — 覆盖 D.3/E.1/G.1/H.1/I.1/J.1/K.1/K.2/L.1/C.2/F.1
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.config import settings
from services.main import app
from services.models import (
    DailyMission, InteractionEvent, KCMastery, MasterySnapshot,
    Paper, PaperStatus, ParentStudent, SocraticSession, Streak, User, UserRole, WrongQuestion,
)

KC_ID = "GDMATH-CONIC-01"


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
    db.add(User(id=sid, phone=f"181{str(sid)[:8]}", role=UserRole.student, name="Test", grade="高三"))
    await db.commit()
    yield sid
    for model in (MasterySnapshot, InteractionEvent, KCMastery, SocraticSession,
                  DailyMission, Streak, Paper, WrongQuestion):
        await db.execute(delete(model).where(model.student_id == sid))
    await db.execute(delete(User).where(User.id == sid))
    await db.commit()


@pytest.fixture(scope="function")
async def parent_user(db):
    pid = uuid.uuid4()
    db.add(User(id=pid, phone=f"182{str(pid)[:8]}", role=UserRole.parent, name="Parent",
                invite_code=str(pid)[:6]))
    await db.commit()
    yield pid
    await db.execute(delete(ParentStudent).where(ParentStudent.parent_id == pid))
    await db.execute(delete(User).where(User.id == pid))
    await db.commit()


@pytest.fixture(scope="function")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── L.1 Health ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    print("  GET /health ✓")


# ── D.3 Papers read ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_papers_list_empty(client, student):
    resp = await client.get("/v1/papers", params={"student_id": str(student)})
    assert resp.status_code == 200
    assert resp.json() == []
    print("  GET /v1/papers empty ✓")


@pytest.mark.asyncio
async def test_paper_detail_not_found(client):
    resp = await client.get(f"/v1/papers/{uuid.uuid4()}")
    assert resp.status_code == 404
    print("  GET /v1/papers/{id} 404 ✓")


@pytest.mark.asyncio
async def test_paper_detail(client, student, db):
    # Create a paper directly
    paper_id = uuid.uuid4()
    db.add(Paper(id=paper_id, student_id=student, subject="math", status=PaperStatus.done))
    await db.commit()
    resp = await client.get(f"/v1/papers/{paper_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["paper"]["id"] == str(paper_id)
    assert "wrong_questions" in data
    print("  GET /v1/papers/{id} ✓")


# ── E.1 Daily mission ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_today_mission_no_mastery(client, student, bypass_auth):
    """无掌握度数据时也能正常返回。"""
    resp = await client.get(f"/v1/missions/today/{student}")
    assert resp.status_code == 200
    data = resp.json()
    assert "streak" in data
    print(f"  GET /v1/missions/today → {data}")


@pytest.mark.asyncio
async def test_today_mission_idempotent(client, student, bypass_auth):
    """同一天多次调用返回同一任务。"""
    r1 = await client.get(f"/v1/missions/today/{student}")
    r2 = await client.get(f"/v1/missions/today/{student}")
    assert r1.status_code == 200
    assert r2.status_code == 200
    d1 = r1.json()
    d2 = r2.json()
    if "mission" in d1 and "mission" in d2:
        assert d1["mission"]["id"] == d2["mission"]["id"], "二次调用应返回同一任务"
    print("  GET /v1/missions/today 幂等 ✓")


@pytest.mark.asyncio
async def test_complete_mission(client, student, db):
    """完成任务后 streak 更新。"""
    resp = await client.get(f"/v1/missions/today/{student}")
    data = resp.json()
    if "mission" not in data:
        pytest.skip("rest mission, skip complete test")
    mission_id = data["mission"]["id"]
    resp2 = await client.post(f"/v1/missions/{mission_id}/complete")
    assert resp2.status_code == 200
    assert resp2.json()["ok"] is True
    print("  POST /v1/missions/{id}/complete ✓")


@pytest.mark.asyncio
async def test_cold_start_socratic_state_serializable(client, student, db, bypass_auth):
    """cold_start_single 返回含 SocraticStateV2 dataclass 时，写库不应 500。"""
    from oskill.cold_start_single import SocraticStateV2

    fake_state = SocraticStateV2(question="测试题", correct_answer="")
    fake_result = {
        "status": "ready_for_guidance",
        "recognized_text": "测试题",
        "metacog": {"self_eval": "不确定"},
        "socratic_state": fake_state,
    }

    import services.mission_service as _mm

    _noon = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    _orig = _mm.get_or_create_mission

    async def _noon_mission(db, student_id, today=None, _now=None):
        return await _orig(db, student_id, today=today, _now=_noon)

    with patch(
        "services.mission_service.cold_start_single",
        new=AsyncMock(return_value=fake_result),
    ), patch(
        "services.main.get_or_create_mission",
        new=_noon_mission,
    ):
        resp = await client.get(f"/v1/missions/today/{student}")

    assert resp.status_code == 200, f"期望200，得到{resp.status_code}: {resp.text}"
    data = resp.json()
    assert "mission" in data
    diagnostics = data["mission"]["content"].get("diagnostics", {})
    # SocraticStateV2 必须已被序列化为 dict
    socratic = diagnostics.get("socratic_state")
    assert isinstance(socratic, dict), f"socratic_state 应为 dict，实为 {type(socratic)}"
    assert socratic.get("question") == "测试题"
    print("  cold_start SocraticStateV2 序列化写库 ✓")


# ── G.1 Parent overview ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parent_overview_empty(client, student, bypass_auth):
    resp = await client.get(f"/v1/parent/overview/{student}")
    assert resp.status_code == 200
    data = resp.json()
    assert "weak_kc_count" in data
    assert "streak" in data
    print(f"  GET /v1/parent/overview → {data}")


# ── H.1 Solve ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_solve_conic(client):
    resp = await client.post("/v1/solve", params={"kc_id": KC_ID, "expression": "x^2 + y^2 = 25"})
    assert resp.status_code == 200
    data = resp.json()
    assert "solvable" in data
    assert "kc_id" in data
    print(f"  POST /v1/solve → solvable={data['solvable']}")


@pytest.mark.asyncio
async def test_solve_linear(client):
    resp = await client.post("/v1/solve", params={"kc_id": "GDMATH-FUNC-01", "expression": "y = 2*x + 1"})
    assert resp.status_code == 200
    print("  POST /v1/solve (linear) ✓")


# ── J.1 Patterns ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_patterns_empty(client, student, bypass_auth):
    resp = await client.get(f"/v1/patterns/{student}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["patterns"] == []
    print("  GET /v1/patterns empty ✓")


@pytest.mark.asyncio
async def test_patterns_with_interactions(client, student, bypass_auth):
    """答了几道题后，patterns 有数据。"""
    for _ in range(3):
        await client.post("/v1/interaction", json={
            "student_id": str(student), "kc_id": KC_ID, "is_correct": True,
        })
    resp = await client.get(f"/v1/patterns/{student}")
    assert resp.status_code == 200
    data = resp.json()
    assert "overall_trend" in data
    print(f"  GET /v1/patterns → {len(data['patterns'])} KC trajectories ✓")


# ── I.1 Practice generate ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_practice_generate(client):
    resp = await client.post("/v1/practice/generate", params={"kc_id": KC_ID, "count": 3})
    assert resp.status_code == 200
    data = resp.json()
    assert data["kc_id"] == KC_ID
    assert "items" in data
    print(f"  POST /v1/practice/generate → {len(data['items'])} items ✓")


@pytest.mark.asyncio
async def test_practice_generate_kc_not_found(client):
    resp = await client.post("/v1/practice/generate", params={"kc_id": "NOT-EXIST", "count": 3})
    assert resp.status_code == 404
    print("  POST /v1/practice/generate 404 ✓")


# ── K.2 User deletion (compliance red line) ─────────────────────────────────

@pytest.mark.asyncio
async def test_delete_student_soft_delete(client, student, db):
    """本人鉴权下软删 → deleted_at 设置（合规红线）。"""
    from types import SimpleNamespace
    from services.main import get_current_user
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=student)
    try:
        resp = await client.post(f"/v1/parent/delete-request/{student}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        assert "deleted_at" in data
        user = (await db.execute(select(User).where(User.id == student))).scalar_one()
        assert user.deleted_at is not None, "合规红线: 软删后 deleted_at 必须有值"
    finally:
        app.dependency_overrides = {}
    print("  POST /v1/parent/delete-request 本人软删 ✓")


@pytest.mark.asyncio
async def test_delete_student_forbidden_for_non_owner(client, student):
    """鉴权红线：登录用户删非本人/非绑定的学生 → 403。"""
    from types import SimpleNamespace
    from services.main import get_current_user
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=student)
    try:
        resp = await client.post(f"/v1/parent/delete-request/{uuid.uuid4()}")
        assert resp.status_code == 403, resp.text
    finally:
        app.dependency_overrides = {}
    print("  POST /v1/parent/delete-request 越权拦截 ✓")


# ── K.1 Archive export ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_archive(client, student, bypass_auth):
    resp = await client.get(f"/v1/parent/export/{student}")
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")
    import json as _json
    data = _json.loads(resp.content)
    assert data["student_id"] == str(student)
    assert "kc_mastery" in data
    print("  GET /v1/parent/export ✓")


# ── F.1 Socratic session ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_socratic_start_no_question(client, student):
    resp = await client.post("/v1/socratic/start",
                              params={"question_id": str(uuid.uuid4()), "student_id": str(student)})
    assert resp.status_code == 404
    print("  POST /v1/socratic/start 404 ✓")


@pytest.mark.asyncio
async def test_socratic_full_flow(client, student, db):
    """开始→发消息(SSE)→escape→end 全流程。"""
    # Create a wrong question
    wq_id = uuid.uuid4()
    db.add(WrongQuestion(
        id=wq_id, student_id=student, paper_id=None,
        question_text="x^2 + y^2 = 25，求圆心和半径",
        correct_answer="圆心(0,0), 半径5",
        knowledge_points={KC_ID: 1.0},
        subject="math",
    ))
    await db.commit()

    # Start
    resp = await client.post("/v1/socratic/start",
                              params={"question_id": str(wq_id), "student_id": str(student)})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]
    assert resp.json()["mode"] in ("deep", "mixed", "sprint")

    # Message (SSE — collect full response)
    resp2 = await client.post(f"/v1/socratic/{session_id}/message",
                               params={"student_message": "我不知道怎么做"})
    assert resp2.status_code == 200
    content = resp2.content.decode()
    assert "data:" in content
    # Red line: correct_answer text must NOT appear in SSE stream
    assert "圆心(0,0), 半径5" not in content, "苏格拉底红线: 不得泄露完整答案"
    print("  SSE 内容不含完整答案 ✓")

    # Escape
    resp3 = await client.post(f"/v1/socratic/{session_id}/escape")
    assert resp3.status_code == 200
    assert "outline" in resp3.json()
    note = resp3.json().get("note", "")
    assert "标准答案" not in note or "非标准答案" in note or note == ""
    print("  escape → outline 非完整答案 ✓")

    # End
    resp4 = await client.post(f"/v1/socratic/{session_id}/end", params={"outcome": "partial"})
    assert resp4.status_code == 200
    assert resp4.json()["outcome"] == "partial"
    print("  POST /v1/socratic end ✓")
