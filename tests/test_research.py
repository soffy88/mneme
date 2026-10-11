"""研究报告（/v1/research）：只引用检索到的教材切片、无依据不编造、限额、鉴权、红线。

真实测试库（research_reports 表），检索与 LLM 用替身注入；夹具自建自清。
"""

from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

from obase.auth import create_access_token
from obase.db import SessionLocal
from services import research_service as svc
from services.main import app
from services.models import User, UserRole

_ROOT = Path(__file__).parent.parent

SOURCES = [
    {"id": "S1", "chunk_id": "chunk-a", "pdf_id": "pdf-1", "book_name": "数学八年级下册",
     "subject": "math", "grade": "G8", "page_number": 24, "score": 0.8, "verified": False,
     "excerpt": "勾股定理：如果直角三角形的两条直角边长分别为a，b，斜边长为c，那么a²+b²=c²。"},
    {"id": "S2", "chunk_id": "chunk-b", "pdf_id": "pdf-1", "book_name": "数学八年级下册",
     "subject": "math", "grade": "G8", "page_number": 25, "score": 0.6, "verified": True,
     "excerpt": "我国古代数学家赵爽用弦图证明了勾股定理，通过拼图使面积相等。"},
]


def _h(user_id: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}


class FakeCaller:
    model = "fake-model"
    last_good_model = "fake-model"

    def __init__(self, payload=None, exc: Exception | None = None, raw: str | None = None):
        self.payload = payload
        self.exc = exc
        self.raw = raw
        self.calls: list[dict] = []

    async def __call__(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        content = self.raw if self.raw is not None else json.dumps(self.payload, ensure_ascii=False)
        return {"content": content, "usage": {"input_tokens": 1000, "output_tokens": 300}}


GOOD = {
    "title": "勾股定理的证明",
    "summary": {"text": "勾股定理说的是直角三角形两条直角边的平方和等于斜边的平方。",
                "sources": ["S1"]},
    "sections": [
        {"heading": "赵爽弦图", "points": [
            {"text": "赵爽用弦图通过拼图面积相等证明了勾股定理。", "sources": ["S2"]},
            {"text": "毕达哥拉斯用了另一种方法。", "sources": ["S9"]},
            {"text": "还有总统证法。", "sources": []},
        ]},
    ],
    "gaps": ["教材没有讲欧几里得的证法"],
}


# ── 纯逻辑：引用只来自检索切片 ─────────────────────────────────────────────


def test_validate_report_only_keeps_retrieved_citations():
    rep = svc.validate_report(GOOD, SOURCES)
    retrieved = {s["chunk_id"] for s in SOURCES}
    cited = []
    for p in [rep["summary"], *[p for sec in rep["sections"] for p in sec["points"]]]:
        assert p["sources"], "保留下来的每条论断都必须有引用"
        for c in p["citations"]:
            cited.append(c["chunk_id"])
            assert c["chunk_id"] in retrieved
            assert c["book_name"] and c["page_number"] is not None
    assert set(cited) == {"chunk-a", "chunk-b"}
    # 编造编号 S9 被剔除、无引用的论断被移入 unsupported 并标注
    texts = {u["text"] for u in rep["unsupported"]}
    assert "毕达哥拉斯用了另一种方法。" in texts and "还有总统证法。" in texts
    assert all(u["note"] == svc.UNSUPPORTED_NOTE for u in rep["unsupported"])
    assert rep["dropped_refs"] == ["S9"]


def test_validate_report_handles_garbage_shapes():
    rep = svc.validate_report({"sections": ["x", {"points": "y"}], "summary": 3}, SOURCES)
    assert rep["sections"] == [] and rep["summary"] is None


async def test_no_sources_means_no_llm_call():
    caller = FakeCaller(GOOD)
    out = await svc.generate_report(None, "量子纠缠是什么", caller=caller, sources=[])
    assert out["status"] == "no_sources"
    assert caller.calls == []
    assert svc.NO_SOURCE_MESSAGE in out["report"]["gaps"]


async def test_prompt_contains_only_retrieved_excerpts(monkeypatch):
    async def no_persona(db, slug):
        return None

    monkeypatch.setattr(svc, "_persona_block", no_persona)
    caller = FakeCaller(GOOD)
    out = await svc.generate_report(None, "勾股定理的证明方法", grade="G8", caller=caller,
                                    sources=SOURCES)
    assert out["status"] == "ready"
    user_msg = caller.calls[0]["messages"][0]["content"]
    assert "[S1]" in user_msg and "[S2]" in user_msg and "[S3]" not in user_msg
    assert "G8" in caller.calls[0]["system"]
    assert out["cost_usd"] > 0


@pytest.mark.parametrize("caller", [
    FakeCaller(exc=RuntimeError("all text endpoints failed")),
    FakeCaller(raw=""),
    FakeCaller(raw="not json at all"),
    FakeCaller({"title": "x", "sections": [{"heading": "h", "points": [
        {"text": "完全编造", "sources": ["S7"]}]}]}),
])
async def test_llm_failure_degrades_to_extractive_quotes(monkeypatch, caller):
    async def no_persona(db, slug):
        return None

    monkeypatch.setattr(svc, "_persona_block", no_persona)
    out = await svc.generate_report(None, "勾股定理", caller=caller, sources=SOURCES)
    assert out["status"] == "extractive"
    pts = out["report"]["sections"][0]["points"]
    for p in pts:
        src = next(s for s in SOURCES if s["id"] == p["sources"][0])
        # 摘录是教材原文的子串（无生成内容）
        assert p["text"] in src["excerpt"]


# ── 红线：研究不进门控 ────────────────────────────────────────────────────

_FORBIDDEN = ("mastery_gate", "gate_store", "math_grade", "verdict_guard", "cognitive_service",
              "process_interaction", "answer_match", "kc_mastery", "fsrs", "evidence")
_NO_WEB = ("httpx", "requests", "urllib", "aiohttp", "web_search")


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(a.name for a in node.names)
    return names


@pytest.mark.parametrize("rel", ["services/research_service.py", "services/routers/research.py"])
def test_research_never_imports_gating_or_web_modules(rel):
    imported = _imports(_ROOT / rel)
    hits = [n for n in _FORBIDDEN if any(n in imp for imp in imported)]
    assert not hits, f"{rel} import 了门控/判分模块 {hits}——违反红线"
    web = [n for n in _NO_WEB if any(imp == n or imp.startswith(n + ".") for imp in imported)]
    assert not web, f"{rel} 不得联网（只用本地教材库）：{web}"


def test_research_sql_never_writes_learning_state():
    src = (_ROOT / "services/research_service.py").read_text(encoding="utf-8").lower()
    for table in ("kc_mastery", "interaction_events", "memory_evidence", "gate.", "mastery_snapshots"):
        assert table not in src


def test_research_reports_in_purge_inventory():
    from services.purge_service import _STUDENT_TABLES

    assert ("research_reports", "student_id") in _STUDENT_TABLES


def test_migration_head_is_expected():
    from services.routers.health import EXPECTED_MIGRATION_HEAD

    versions = (_ROOT / "alembic" / "versions").glob("*.py")
    revisions, downs = set(), set()
    for f in versions:
        s = f.read_text(encoding="utf-8")
        for line in s.splitlines():
            if line.startswith("revision = "):
                revisions.add(line.split("=", 1)[1].strip().strip("\"'"))
            if line.startswith("down_revision = "):
                downs.add(line.split("=", 1)[1].strip().strip("\"'"))
    assert "rsr1a2b3c4d5" in revisions
    assert EXPECTED_MIGRATION_HEAD not in downs, "EXPECTED_MIGRATION_HEAD 必须是迁移链的 head"


# ── 路由（真实测试库） ─────────────────────────────────────────────────────


@pytest.fixture
async def world(monkeypatch):
    a, b, parent, admin = (uuid.uuid4() for _ in range(4))
    monkeypatch.setenv("ADMIN_USER_IDS", str(admin))
    monkeypatch.setenv("MNEME_RESEARCH_DAILY_LIMIT", "2")
    monkeypatch.delenv("MNEME_RESEARCH_DAILY_USD", raising=False)
    caller = FakeCaller(GOOD)

    async def fake_retrieve(db, question, *, k=None):
        return [] if "无关" in question else [dict(s) for s in SOURCES]

    async def no_persona(db, slug):
        return None

    monkeypatch.setattr(svc, "retrieve_sources", fake_retrieve)
    monkeypatch.setattr(svc, "_persona_block", no_persona)
    import services.providers.setup as provider_setup

    monkeypatch.setattr(provider_setup, "get_optional_text_caller", lambda: caller)

    async with SessionLocal() as db:
        db.add(User(id=a, role=UserRole.student, name="研究A", grade="G8"))
        db.add(User(id=b, role=UserRole.student, name="研究B"))
        db.add(User(id=parent, role=UserRole.parent, name="家长"))
        db.add(User(id=admin, role=UserRole.student, name="管理员"))
        await db.commit()
    yield {"a": a, "b": b, "parent": parent, "admin": admin, "caller": caller}
    ids = [str(x) for x in (a, b, parent, admin)]
    async with SessionLocal() as db:
        await db.execute(text("DELETE FROM research_reports WHERE student_id = ANY(:ids)"),
                         {"ids": ids})
        await db.execute(delete(User).where(User.id.in_([a, b, parent, admin])))
        await db.commit()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_auth_required_and_parents_forbidden(world, client):
    assert (await client.post("/v1/research", json={"question": "勾股定理"})).status_code == 401
    assert (await client.get("/v1/research")).status_code == 401
    r = await client.post("/v1/research", json={"question": "勾股定理"}, headers=_h(world["parent"]))
    assert r.status_code == 403


async def test_create_get_list_own_only(world, client):
    r = await client.post("/v1/research", json={"question": "勾股定理的证明方法"},
                          headers=_h(world["a"]))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"].startswith("rsr_") and body["status"] == "ready"
    assert body["grade"] == "G8"
    retrieved = {s["chunk_id"] for s in body["sources"]}
    for sec in body["report"]["sections"]:
        for p in sec["points"]:
            assert {c["chunk_id"] for c in p["citations"]} <= retrieved
    assert body["report"]["unsupported"], "无依据的论断必须显式列出"

    got = await client.get(f"/v1/research/{body['id']}", headers=_h(world["a"]))
    assert got.status_code == 200 and got.json()["report"]["title"] == "勾股定理的证明"
    # 别人的报告 → 404（不泄露存在性）
    assert (await client.get(f"/v1/research/{body['id']}", headers=_h(world["b"]))).status_code == 404
    lst = (await client.get("/v1/research", headers=_h(world["a"]))).json()
    assert [i["id"] for i in lst["items"]] == [body["id"]]
    assert lst["used_today"] == 1 and lst["daily_limit"] == 2
    assert (await client.get("/v1/research", headers=_h(world["b"]))).json()["items"] == []


async def test_no_source_question_is_recorded_without_llm(world, client):
    n = len(world["caller"].calls)
    r = await client.post("/v1/research", json={"question": "无关的问题"}, headers=_h(world["a"]))
    assert r.status_code == 201 and r.json()["status"] == "no_sources"
    assert len(world["caller"].calls) == n


async def test_daily_limit_and_admin_exempt(world, client):
    for _ in range(2):
        assert (await client.post("/v1/research", json={"question": "勾股定理"},
                                  headers=_h(world["a"]))).status_code == 201
    r = await client.post("/v1/research", json={"question": "勾股定理"}, headers=_h(world["a"]))
    assert r.status_code == 429
    for _ in range(3):
        assert (await client.post("/v1/research", json={"question": "勾股定理"},
                                  headers=_h(world["admin"]))).status_code == 201


async def test_global_cost_cap(world, client, monkeypatch):
    monkeypatch.setenv("MNEME_RESEARCH_DAILY_USD", "0.000001")
    async with SessionLocal() as db:
        await db.execute(text(
            "INSERT INTO research_reports (id, student_id, question, status, report, sources, cost_usd) "
            "VALUES (:id, :s, 'q', 'ready', '{}'::jsonb, '[]'::jsonb, 0.01)"),
            {"id": "rsr_" + uuid.uuid4().hex[:16], "s": str(world["b"])})
        await db.commit()
    r = await client.post("/v1/research", json={"question": "勾股定理"}, headers=_h(world["a"]))
    assert r.status_code == 503


async def test_validation_and_kid_safety(world, client):
    h = _h(world["a"])
    assert (await client.post("/v1/research", json={"question": "怎么制毒"}, headers=h)).status_code == 422
    assert (await client.post("/v1/research", json={"question": "勾" * 300}, headers=h)).status_code == 422
    assert (await client.post("/v1/research", json={"question": ""}, headers=h)).status_code == 422
    # 被拒的问题不计入限额
    lst = (await client.get("/v1/research", headers=h)).json()
    assert lst["used_today"] == 0
