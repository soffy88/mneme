"""Memory Inspect —— 学生本人可检视 + 可遗忘（对标 DeepTutor Memory 页）。

覆盖：
① services.memory.list_for_student / forget：只列/只删本人行（SQL 层强制 student_id 条件）
② HTTP GET /v2/memory/inspect/{sid}：本人 200；他人（含绑定家长）403；匿名 401
③ HTTP POST /v2/memory/forget：本人删自己的 episodic/semantic/claim → 200 且真删；
   用自己的 student_id 去删别人的 item → 404 且别人的行仍在；替别人删 → 403
④ 遗忘 claim 只删 claim（边级联），不删 memory_evidence 证据行
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text

from obase.auth import create_access_token
from obase.db import SessionLocal
from services import memory
from services.main import app
from services.models import (
    MemoryClaim,
    MemoryClaimEvidence,
    MemoryEvidence,
    ParentStudent,
    User,
    UserRole,
)


def _h(user_id: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}


# ── ① 服务层（单 session 不 commit，退出回滚）────────────────────────────────


@pytest.mark.asyncio
async def test_list_and_forget_are_scoped_to_student():
    async with SessionLocal() as db:
        a, b = uuid.uuid4(), uuid.uuid4()
        ea = await memory.append_episode(db, a, kind="tutor_turn", content={"n": "A"})
        eb = await memory.append_episode(db, b, kind="tutor_turn", content={"n": "B"})
        await memory.update(db, a, topic="algebra", content={"summary": "A 的摘要"})

        view = await memory.list_for_student(db, a)
        assert [e["id"] for e in view["episodic"]] == [ea["id"]]
        assert view["episodic"][0]["content"] == {"n": "A"}
        assert [s["topic"] for s in view["semantic"]] == ["algebra"]

        # A 不能删 B 的行（即使知道 id）
        assert not await memory.forget(
            db, a, layer="episodic", item_id=uuid.UUID(eb["id"])
        )
        assert await memory.forget(db, a, layer="episodic", item_id=uuid.UUID(ea["id"]))
        assert (await memory.list_for_student(db, a))["episodic"] == []
        assert len((await memory.list_for_student(db, b))["episodic"]) == 1

        sem_id = uuid.UUID(view["semantic"][0]["id"])
        assert await memory.forget(db, a, layer="semantic", item_id=sem_id)
        assert (await memory.list_for_student(db, a))["semantic"] == []

        with pytest.raises(ValueError):
            await memory.forget(db, a, layer="working", item_id=uuid.uuid4())
        await db.rollback()


# ── ②③④ HTTP（真提交，夹具清理）─────────────────────────────────────────────


@pytest.fixture
async def actors():
    a, b, p = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=a, phone=f"181{str(a.int)[:8]}", role=UserRole.student, name="A"))
        db.add(User(id=b, phone=f"182{str(b.int)[:8]}", role=UserRole.student, name="B"))
        db.add(User(id=p, phone=f"183{str(p.int)[:8]}", role=UserRole.parent, name="P"))
        await db.flush()
        db.add(ParentStudent(parent_id=p, student_id=a))
        ea = await memory.append_episode(db, a, kind="tutor_turn", content={"n": "A1"})
        eb = await memory.append_episode(db, b, kind="tutor_turn", content={"n": "B1"})
        await memory.update(db, a, topic="函数", content={"summary": "A 熟悉函数定义"})
        now = datetime.now(timezone.utc)
        claim = MemoryClaim(
            student_id=a,
            claim_type="mastery_signal",
            subject_type="knowledge_unit",
            subject_id="ku-test",
            claim_text="A 在 ku-test 上连续答对",
            privacy_class="P1",
        )
        ev = MemoryEvidence(
            student_id=a,
            evidence_type="graded_attempt",
            occurred_at=now,
            privacy_class="P1",
        )
        db.add_all([claim, ev])
        await db.flush()
        db.add(MemoryClaimEvidence(claim_id=claim.id, evidence_id=ev.id))
        claim_id, ev_id = str(claim.id), str(ev.id)
        await db.commit()
        ids = {
            "a": a,
            "b": b,
            "p": p,
            "ea": ea["id"],
            "eb": eb["id"],
            "claim": claim_id,
            "evidence": ev_id,
        }
    yield ids
    async with SessionLocal() as db:
        for tbl in ("agent.episodic_memory", "agent.semantic_memory", "agent.audit_log"):
            await db.execute(
                text(f"DELETE FROM {tbl} WHERE student_id = ANY(:ids)"),  # noqa: S608
                {"ids": [a, b, p]},
            )
        await db.execute(delete(MemoryClaim).where(MemoryClaim.student_id.in_([a, b])))
        await db.execute(
            delete(MemoryEvidence).where(MemoryEvidence.student_id.in_([a, b]))
        )
        await db.execute(delete(ParentStudent).where(ParentStudent.parent_id == p))
        await db.execute(delete(User).where(User.id.in_([a, b, p])))
        await db.commit()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_inspect_self_only(client, actors):
    a = actors["a"]
    r = await client.get(f"/v2/memory/inspect/{a}", headers=_h(a))
    assert r.status_code == 200
    body = r.json()
    assert [e["id"] for e in body["episodic"]] == [actors["ea"]]
    assert body["semantic"][0]["topic"] == "函数"
    assert body["claims"][0]["id"] == actors["claim"]
    assert body["claims"][0]["evidence_count"] == 1

    assert (await client.get(f"/v2/memory/inspect/{a}", headers=_h(actors["b"]))).status_code == 403
    assert (await client.get(f"/v2/memory/inspect/{a}", headers=_h(actors["p"]))).status_code == 403
    assert (await client.get(f"/v2/memory/inspect/{a}")).status_code == 401


@pytest.mark.asyncio
async def test_forget_own_items_and_never_others(client, actors):
    a, b = actors["a"], actors["b"]

    # 替别人删 → 403
    r = await client.post(
        "/v2/memory/forget",
        json={"student_id": str(b), "layer": "episodic", "item_id": actors["eb"]},
        headers=_h(a),
    )
    assert r.status_code == 403
    # 用自己的 student_id 删别人的 item → 404，别人的行仍在
    r = await client.post(
        "/v2/memory/forget",
        json={"student_id": str(a), "layer": "episodic", "item_id": actors["eb"]},
        headers=_h(a),
    )
    assert r.status_code == 404
    async with SessionLocal() as db:
        assert len((await memory.list_for_student(db, b))["episodic"]) == 1

    # 删自己的 episodic
    r = await client.post(
        "/v2/memory/forget",
        json={"student_id": str(a), "layer": "episodic", "item_id": actors["ea"]},
        headers=_h(a),
    )
    assert r.status_code == 200 and r.json()["forgotten"] is True

    # 删自己的 claim：claim 与边消失，证据行保留
    r = await client.post(
        "/v2/memory/forget",
        json={"student_id": str(a), "layer": "claim", "item_id": actors["claim"]},
        headers=_h(a),
    )
    assert r.status_code == 200
    async with SessionLocal() as db:
        cid, eid = uuid.UUID(actors["claim"]), uuid.UUID(actors["evidence"])
        assert (await db.execute(select(MemoryClaim).where(MemoryClaim.id == cid))).first() is None
        assert (
            await db.execute(
                select(MemoryClaimEvidence).where(MemoryClaimEvidence.claim_id == cid)
            )
        ).first() is None
        assert (
            await db.execute(select(MemoryEvidence).where(MemoryEvidence.id == eid))
        ).first() is not None

    body = (await client.get(f"/v2/memory/inspect/{a}", headers=_h(a))).json()
    assert body["episodic"] == [] and body["claims"] == []
    assert len(body["semantic"]) == 1  # 没删的仍在

    # 非法 layer → 422
    r = await client.post(
        "/v2/memory/forget",
        json={"student_id": str(a), "layer": "working", "item_id": actors["ea"]},
        headers=_h(a),
    )
    assert r.status_code == 422


def test_memory_inspect_module_never_imports_gating_modules():
    """memory_inspect 与 services/memory.py 同红线：不 import 门控/判分模块。"""
    import ast
    from pathlib import Path

    src = (Path(__file__).parent.parent / "services" / "memory_inspect.py").read_text(
        encoding="utf-8"
    )
    names: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(a.name for a in node.names)
    forbidden = ("mastery_gate", "gate_store", "math_grade", "verdict_guard",
                 "cognitive_service", "process_interaction", "answer_match")
    assert not [f for f in forbidden if any(f in n for n in names)]
