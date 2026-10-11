"""题目收藏（☆，/v2/practice/bookmarks）：仅本人、幂等、purge 覆盖、队列带出、永不含答案。"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

from obase.auth import create_access_token
from obase.db import SessionLocal
from services.main import app
from services.models import User, UserRole, WrongQuestion


def _h(u: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(u)})}"}


@pytest.fixture
async def pair():
    a, b = uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=a, phone=f"177{str(a.int)[:8]}", role=UserRole.student))
        db.add(User(id=b, phone=f"178{str(b.int)[:8]}", role=UserRole.student))
        await db.flush()
        wa = WrongQuestion(student_id=a, question_text="求 2x=4 的解", correct_answer="SECRET_A",
                           student_answer="x=3", knowledge_points={"bm-kc": 1.0})
        wb = WrongQuestion(student_id=b, question_text="别人的错题", correct_answer="SECRET_B",
                           knowledge_points={"bm-kc": 1.0})
        db.add_all([wa, wb])
        await db.flush()
        wa_id, wb_id = str(wa.id), str(wb.id)
        await db.execute(
            text("INSERT INTO gate.pending_question (question_id, student_id, kc_id, prompt, expected, qtype) "
                 "VALUES (:q, CAST(:s AS uuid), 'bm-kc2', '3+4=?', 'SECRET_P', 'solve')"),
            {"q": f"q-bm-{a.hex[:12]}", "s": str(a)},
        )
        await db.commit()
        ids = {"a": a, "b": b, "wa": wa_id, "wb": wb_id, "qa": f"q-bm-{a.hex[:12]}"}
    yield ids
    async with SessionLocal() as db:
        for u in (a, b):
            await db.execute(text("DELETE FROM question_bookmarks WHERE student_id = :s"), {"s": u})
            await db.execute(text("DELETE FROM gate.pending_question WHERE student_id = CAST(:s AS uuid)"), {"s": str(u)})
        await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id.in_([a, b])))
        await db.execute(delete(User).where(User.id.in_([a, b])))
        await db.commit()


@pytest.mark.asyncio
async def test_bookmark_crud_owner_only_and_no_answers(pair):
    a, b = pair["a"], pair["b"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.post("/v2/practice/bookmarks", json={"student_id": str(a), "source": "wrong", "question_id": pair["wa"]}, headers=_h(a))
        assert r1.status_code == 201, r1.text
        bm = r1.json()
        assert bm["kc_id"] == "bm-kc" and bm["prompt"] == "求 2x=4 的解"
        # 幂等
        r1b = await c.post("/v2/practice/bookmarks", json={"student_id": str(a), "source": "wrong", "question_id": pair["wa"]}, headers=_h(a))
        assert r1b.json()["id"] == bm["id"]
        # posed：题干从服务端 pending 取
        r2 = await c.post("/v2/practice/bookmarks", json={"student_id": str(a), "source": "posed", "question_id": pair["qa"]}, headers=_h(a))
        assert r2.status_code == 201 and r2.json()["prompt"] == "3+4=?" and r2.json()["kc_id"] == "bm-kc2"

        # 越权：收藏别人的错题 → 404；替别人收藏 → 403；未登录 → 401
        assert (await c.post("/v2/practice/bookmarks", json={"student_id": str(a), "source": "wrong", "question_id": pair["wb"]}, headers=_h(a))).status_code == 404
        assert (await c.post("/v2/practice/bookmarks", json={"student_id": str(a), "source": "wrong", "question_id": pair["wa"]}, headers=_h(b))).status_code == 403
        assert (await c.post("/v2/practice/bookmarks", json={"student_id": str(a), "source": "wrong", "question_id": pair["wa"]})).status_code == 401
        assert (await c.post("/v2/practice/bookmarks", json={"student_id": str(a), "source": "posed", "question_id": "q-nope"}, headers=_h(a))).status_code == 404
        assert (await c.post("/v2/practice/bookmarks", json={"student_id": str(a), "source": "other", "question_id": "x"}, headers=_h(a))).status_code == 422

        lst = await c.get(f"/v2/practice/bookmarks/{a}", headers=_h(a))
        assert lst.status_code == 200 and len(lst.json()["bookmarks"]) == 2
        assert (await c.get(f"/v2/practice/bookmarks/{a}", headers=_h(b))).status_code == 403

        q = await c.get(f"/v2/practice/queue/{a}", headers=_h(a))
        body = q.json()
        assert {x["id"] for x in body["bookmarks"]} == {bm["id"], r2.json()["id"]}
        assert body["wrong_questions"][0]["bookmarked"] is True
        for resp in (r1, r2, lst, q):
            blob = resp.text
            assert "SECRET" not in blob and "correct_answer" not in blob and "expected" not in blob
            assert "别人的错题" not in blob

        # 删除：别人删 → 404（不泄露存在性），本人删 → 200，再删 → 404
        assert (await c.delete(f"/v2/practice/bookmarks/{bm['id']}", headers=_h(b))).status_code == 404
        assert (await c.delete(f"/v2/practice/bookmarks/{bm['id']}", headers=_h(a))).status_code == 200
        assert (await c.delete(f"/v2/practice/bookmarks/{bm['id']}", headers=_h(a))).status_code == 404
        assert (await c.delete(f"/v2/practice/bookmarks/{bm['id']}")).status_code == 401


@pytest.mark.asyncio
async def test_bookmark_table_never_stores_answers(pair):
    a = pair["a"]
    from services.bookmark_service import add_bookmark

    async with SessionLocal() as db:
        await add_bookmark(db, a, "wrong", pair["wa"])
        await add_bookmark(db, a, "posed", pair["qa"])
        rows = (await db.execute(text("SELECT * FROM question_bookmarks WHERE student_id = :s"), {"s": a})).mappings().all()
        assert len(rows) == 2
        assert "SECRET" not in repr([dict(r) for r in rows])
        await db.rollback()


def test_bookmarks_in_purge_inventory():
    from services.purge_service import _STUDENT_TABLES

    assert ("question_bookmarks", "student_id") in _STUDENT_TABLES


@pytest.mark.asyncio
async def test_purge_removes_bookmarks(pair):
    from services.bookmark_service import add_bookmark
    from services.purge_service import _STUDENT_TABLES

    a = pair["a"]
    async with SessionLocal() as db:
        await add_bookmark(db, a, "wrong", pair["wa"])
        # 只跑清单里本表那一步（完整 purge 链路由 purge 测试覆盖）
        for table, col in _STUDENT_TABLES:
            if table == "question_bookmarks":
                await db.execute(text(f"DELETE FROM {table} WHERE {col} = ANY(:ids)"), {"ids": [str(a)]})
        n = (await db.execute(text("SELECT count(*) FROM question_bookmarks WHERE student_id = :s"), {"s": a})).scalar()
        assert n == 0
        await db.rollback()


def test_bookmark_module_no_gating_coupling():
    import services.bookmark_service as bs

    names: set[str] = set()
    for node in ast.walk(ast.parse(Path(bs.__file__).read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    for bad in ("mastery_gate", "gate_store", "verdict_guard", "cognitive_service", "math_grade", "answer_match"):
        assert not any(bad in n for n in names), bad
    src = Path(bs.__file__).read_text(encoding="utf-8")
    assert "correct_answer" not in src.split('"""', 2)[2] and "expected" not in src.split('"""', 2)[2]
