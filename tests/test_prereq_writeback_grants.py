"""CNM-3：先修诊断作答逐题经 SubmitAnswer 回写 BKT + 4 个 MCP 工具授权 + tutor agent 挂载。

真实 HTTP（同 tests/test_multi_user_mcp.py 写法），打测试库 mneme_test。
"""

from __future__ import annotations

import ast
import pathlib
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
from services.tool_grants import DEFAULT_STUDENT_TOOLS, PREREQ_DIAGNOSIS_TOOLS

from .db_test_helpers import cleanup_test_student

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = sorted(PREREQ_DIAGNOSIS_TOOLS)


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
    db.add(User(id=stu, role=UserRole.student, name="诊断学生"))
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


def _answer_of(qid: str) -> str:
    q = pds.question_by_id(qid)
    assert q is not None
    return str(q["answer"])


async def _start(client, user, target="cnmath:cnm_p001", limit=5):
    r = await client.post("/v1/placement/prereq/start", json={"targets": [target], "limit": limit}, headers=_h(user))
    assert r.status_code == 200, r.text
    return r.json()


async def _mastery(db, sid, kc):
    db.expire_all()
    return (
        await db.execute(select(KCMastery).where(KCMastery.student_id == sid, KCMastery.knowledge_point == kc))
    ).scalars().first()


# ----------------------------------------------------------------- 1. BKT 回写（逐题、只经 SubmitAnswer）


@pytest.mark.asyncio
async def test_auto_graded_answer_writes_mastery_via_submit_answer(actors, client, db):
    stu = actors["stu"]
    st = await _start(client, stu)
    nxt = st["next"]
    # 挑一道能自动判的题：首题若是 self 题则 skip 推进（自评不回写）
    session = st["session"]
    if nxt["question"]["type"] == "self":
        pytest.skip("首题为自评题")
    ans = _answer_of(nxt["question"]["id"])
    r = await client.post("/v1/placement/prereq/answer", json={"session": session, "answer": ans}, headers=_h(stu))
    assert r.status_code == 200, r.text
    body = r.json()
    wb = body["mastery_writeback"]
    assert wb["written"] is True and wb["kc_id"] == "cnmath:cnm_p001" and wb["is_correct"] is True
    assert wb["verdict_source"] == "deterministic"
    assert body["report"]["is_mastery_estimate"] is False
    row = await _mastery(db, stu, "cnmath:cnm_p001")
    assert row is not None and 0 < (row.p_mastery or 0) <= 0.97
    # pending 已清（SubmitAnswer 路径 clear_pending）
    left = (await db.execute(text("SELECT count(*) FROM gate.pending_question WHERE student_id=:s"), {"s": stu})).scalar()
    assert left == 0
    # 客户端重放同一步：不重复写
    r2 = await client.post("/v1/placement/prereq/answer", json={"session": session, "answer": ans}, headers=_h(stu))
    assert r2.json()["mastery_writeback"] == {"written": False, "reason": "duplicate", "question_id": wb["question_id"]}
    n_events = (await db.execute(text("SELECT count(*) FROM interaction_events WHERE student_id=:s"), {"s": stu})).scalar()
    assert n_events == 1


@pytest.mark.asyncio
async def test_wrong_answer_lowers_and_self_assessment_never_writes(actors, client, db):
    stu = actors["stu"]
    st = await _start(client, stu, "cnm_221", limit=10)
    r = await client.post("/v1/placement/prereq/answer", json={"session": st["session"], "result": "wrong"}, headers=_h(stu))
    assert r.json()["mastery_writeback"]["reason"] == "self_assessed"
    assert await _mastery(db, stu, "cnmath:cnm_221") is None
    s2 = r.json()["session"]
    q2 = r.json()["next"]["question"]
    if q2["type"] in ("numeric", "choice"):
        right = _answer_of(q2["id"])
        # 选择题要给合法但错误的选项键（非法键判题不推进 → not_applied）
        bad = next(c["key"] for c in q2["choices"] if c["key"] != right) if q2["type"] == "choice" else "-98765"
        r3 = await client.post("/v1/placement/prereq/answer", json={"session": s2, "answer": bad}, headers=_h(stu))
        wb = r3.json()["mastery_writeback"]
        assert wb["written"] is True and wb["is_correct"] is False, (q2, wb)
        assert (await _mastery(db, stu, "cnmath:cnm_221")) is not None


@pytest.mark.asyncio
async def test_parent_and_opt_out_never_write(actors, client, db):
    st = await _start(client, actors["par"])
    ans = _answer_of(st["next"]["question"]["id"])
    r = await client.post("/v1/placement/prereq/answer", json={"session": st["session"], "answer": ans}, headers=_h(actors["par"]))
    assert r.json()["mastery_writeback"] == {"written": False, "reason": "not_student"}
    stu = actors["stu"]
    st = await _start(client, stu)
    r = await client.post(
        "/v1/placement/prereq/answer",
        json={"session": st["session"], "answer": "x", "record_mastery": False},
        headers=_h(stu),
    )
    assert r.json()["mastery_writeback"]["reason"] == "disabled"
    assert await _mastery(db, stu, "cnmath:cnm_p001") is None


def test_writeback_only_through_submit_answer_path():
    """红线：回写函数只调 gate_store.pose_question + tool_submit_answer，不直调 process_interaction/kc_mastery。"""
    src = (ROOT / "services/mcp_router.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "prereq_mastery_writeback")
    called = {
        (c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", ""))
        for c in ast.walk(fn)
        if isinstance(c, ast.Call)
    }
    assert "tool_submit_answer" in called and "pose_question" in called
    assert not called & {"process_interaction", "cognitive_update", "bkt_update", "get_or_create"}
    assert "KCMastery" not in ast.unparse(fn)


# ----------------------------------------------------------------- 2. MCP 工具授权 + tutor agent 挂载


@pytest.mark.asyncio
async def test_students_get_default_grant_parents_denied(actors, client):
    for tool, payload in (
        ("SearchMathTopic", {"q": "配方法"}),
        ("GetMathTopic", {"topic_id": "cnm_221"}),
        ("StartPrereqDiagnosis", {"targets": ["cnm_221"]}),
    ):
        ok = await client.post(f"/mcp/{tool}", json=payload, headers=_h(actors["stu"]))
        assert ok.status_code == 200, (tool, ok.text)
        no = await client.post(f"/mcp/{tool}", json=payload, headers=_h(actors["par"]))
        assert no.status_code == 403, tool
    ok = await client.post("/mcp/SearchMathTopic", json={"q": "配方法"}, headers=_h(actors["admin"]))
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_admin_set_user_grant_restricts_and_extends(actors, client):
    stu, par, adm = actors["stu"], actors["par"], actors["admin"]
    r = await client.post(
        "/mcp/SetUserGrant", json={"student_id": str(stu), "enabled_tools": ["SearchMathTopic"]}, headers=_h(adm)
    )
    assert r.status_code == 200, r.text
    assert (await client.post("/mcp/SearchMathTopic", json={"q": "配方"}, headers=_h(stu))).status_code == 200
    assert (await client.post("/mcp/StartPrereqDiagnosis", json={"targets": ["cnm_221"]}, headers=_h(stu))).status_code == 403
    # 家长经显式授权可用
    r = await client.post(
        "/mcp/SetUserGrant", json={"student_id": str(par), "enabled_tools": TOOLS}, headers=_h(adm)
    )
    assert r.status_code == 200
    st = await client.post("/mcp/StartPrereqDiagnosis", json={"targets": ["cnm_p001"], "limit": 5}, headers=_h(par))
    assert st.status_code == 200
    sub = await client.post(
        "/mcp/SubmitPrereqDiagnosisAnswer", json={"session": st.json()["session"], "result": "skip"}, headers=_h(par)
    )
    assert sub.status_code == 200 and sub.json()["mastery_writeback"]["written"] is False


@pytest.mark.asyncio
async def test_mcp_submit_writes_for_student(actors, client, db):
    stu = actors["stu"]
    st = (await client.post("/mcp/StartPrereqDiagnosis", json={"targets": ["cnm_p001"], "limit": 5}, headers=_h(stu))).json()
    q = st["next"]["question"]
    if q["type"] == "self":
        pytest.skip("首题为自评题")
    sub = await client.post(
        "/mcp/SubmitPrereqDiagnosisAnswer",
        json={"session": st["session"], "answer": _answer_of(q["id"])},
        headers=_h(stu),
    )
    assert sub.status_code == 200 and sub.json()["mastery_writeback"]["written"] is True
    assert await _mastery(db, stu, "cnmath:cnm_p001") is not None


def test_default_student_tools_are_the_four_diagnosis_tools():
    assert PREREQ_DIAGNOSIS_TOOLS == {
        "SearchMathTopic", "GetMathTopic", "StartPrereqDiagnosis", "SubmitPrereqDiagnosisAnswer"
    }
    # AetherViz 起学生默认集 = 4 个诊断工具 + GenerateKUVisualization；
    # 缺口单点练闭环起再加 3 个 GapDrill 工具（同为无状态+SubmitAnswer 写路径）
    from services.tool_grants import GAP_DRILL_TOOLS

    assert DEFAULT_STUDENT_TOOLS == (
        PREREQ_DIAGNOSIS_TOOLS | {"GenerateKUVisualization"} | GAP_DRILL_TOOLS
    )
    assert "BindPartnerChannel" not in DEFAULT_STUDENT_TOOLS


@pytest.mark.asyncio
async def test_tutor_agent_registers_the_four_tools(monkeypatch):
    from mneme_agent.assembly import tutor_loop

    calls: list[tuple[str, dict]] = []

    async def fake_mcp(api_base, tool, payload, auth_token=None):
        calls.append((tool, payload))
        return {"ok": True}

    monkeypatch.setattr(tutor_loop, "_mcp", fake_mcp)
    specs = {s.name: s for s in tutor_loop.build_tools("http://x", student_id="s", kc_ids=[], auth_token="t")}
    assert PREREQ_DIAGNOSIS_TOOLS <= set(specs)
    assert specs["SearchMathTopic"].readonly and specs["GetMathTopic"].readonly
    assert not specs["SubmitPrereqDiagnosisAnswer"].readonly
    await specs["SearchMathTopic"].callable({"q": "配方法"})
    await specs["StartPrereqDiagnosis"].callable({"targets": ["cnm_221"]})
    await specs["SubmitPrereqDiagnosisAnswer"].callable({"session": {"a": 1}, "answer": "4"})
    assert [c[0] for c in calls] == ["SearchMathTopic", "StartPrereqDiagnosis", "SubmitPrereqDiagnosisAnswer"]
    assert calls[2][1] == {"session": {"a": 1}, "answer": "4", "result": None}
