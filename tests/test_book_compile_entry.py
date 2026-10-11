"""活书编译入口：POST /v1/books/compile + GET /v1/books/{id}/status + Celery 任务体。

路由层：鉴权（401/403）、校验（404/422）、去重、per-user 每日限额、全站成本上限、
入队失败兜底。任务层：用 scripted fake caller 跑真实 omodul.book_compile，验证
占位 book_id 稳定（章节挂到占位行、omodul 生成的那一行被并掉）、幂等、单本成本上限。
真实测试库，夹具自建自清。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

from obase.auth import create_access_token
from obase.db import SessionLocal
from services import book_compile_service as svc
from services.main import app
from services.models import KnowledgeCluster, KnowledgeUnit, Textbook, User, UserRole


def _h(user_id: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}


@pytest.fixture
async def world(monkeypatch):
    """两本教材（一本有知识簇、一本没有）+ 学生 A/B、家长、admin。"""
    tag = uuid.uuid4().hex[:8]
    tb_ok, tb_empty = f"tb-bce-{tag}", f"tb-bce0-{tag}"
    admin, a, b, parent = (uuid.uuid4() for _ in range(4))
    monkeypatch.setenv("ADMIN_USER_IDS", str(admin))
    for k in ("MNEME_BOOK_COMPILE_DAILY_LIMIT", "MNEME_BOOK_COMPILE_DAILY_USD",
              "MNEME_BOOK_COMPILE_MAX_USD"):
        monkeypatch.delenv(k, raising=False)

    enqueued: list[str] = []
    monkeypatch.setattr(svc, "enqueue_compile", lambda book_id: enqueued.append(book_id))

    async with SessionLocal() as db:
        for tid in (tb_ok, tb_empty):
            db.add(Textbook(id=tid, subject="math", grade="G1", edition="测试版",
                            book_name=f"入口测试教材{tid[-4:]}"))
        await db.flush()
        db.add(KnowledgeCluster(id=f"{tb_ok}-c1", textbook_id=tb_ok, name="入口测试章节",
                                display_order=1))
        await db.flush()
        for i in range(2):
            db.add(KnowledgeUnit(id=f"{tb_ok}-ku-{i}", textbook_id=tb_ok,
                                 cluster_id=f"{tb_ok}-c1", name=f"KU{i}",
                                 description="入口测试知识点"))
        db.add(User(id=admin, role=UserRole.student, name="管理员"))
        db.add(User(id=a, role=UserRole.student, name="学生A"))
        db.add(User(id=b, role=UserRole.student, name="学生B"))
        db.add(User(id=parent, role=UserRole.parent, name="家长"))
        await db.commit()

    yield {"tb": tb_ok, "tb_empty": tb_empty, "admin": admin, "a": a, "b": b,
           "parent": parent, "enqueued": enqueued}

    async with SessionLocal() as db:
        for tid in (tb_ok, tb_empty):
            await db.execute(text("DELETE FROM books WHERE textbook_id=:t"), {"t": tid})
            await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.textbook_id == tid))
            await db.execute(delete(KnowledgeCluster).where(KnowledgeCluster.textbook_id == tid))
            await db.execute(delete(Textbook).where(Textbook.id == tid))
        await db.execute(delete(User).where(User.id.in_([admin, a, b, parent])))
        await db.commit()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _set_status(book_id: str, status: str) -> None:
    async with SessionLocal() as db:
        await db.execute(text("UPDATE books SET status=:s WHERE id=:id"),
                         {"s": status, "id": book_id})
        await db.commit()


# ---------------- 路由 ----------------

@pytest.mark.asyncio
async def test_unauthenticated_is_401(client):
    r = await client.post("/v1/books/compile", json={"textbook_id": "x"})
    assert r.status_code == 401
    r = await client.get("/v1/books/whatever/status")
    assert r.status_code == 401
    r = await client.get("/v1/books/compile/textbooks")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_unknown_textbook_404_and_no_clusters_422(world, client):
    r = await client.post("/v1/books/compile", json={"textbook_id": "nope-" + uuid.uuid4().hex[:6]},
                          headers=_h(world["a"]))
    assert r.status_code == 404
    r = await client.post("/v1/books/compile", json={"textbook_id": world["tb_empty"]},
                          headers=_h(world["a"]))
    assert r.status_code == 422
    assert world["enqueued"] == []


@pytest.mark.asyncio
async def test_parent_cannot_compile(world, client):
    r = await client.post("/v1/books/compile", json={"textbook_id": world["tb"]},
                          headers=_h(world["parent"]))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_student_compile_queues_and_status_visible(world, client):
    r = await client.post("/v1/books/compile", json={"textbook_id": world["tb"]},
                          headers=_h(world["a"]))
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "queued" and job["deduplicated"] is False
    assert job["book_id"].startswith(svc.PLACEHOLDER_PREFIX)
    assert world["enqueued"] == [job["book_id"]]

    st = (await client.get(f"/v1/books/{job['book_id']}/status", headers=_h(world["a"]))).json()
    assert st["status"] == "queued" and st["requested_by_me"] is True
    assert "requested_by" not in st
    st_b = (await client.get(f"/v1/books/{job['book_id']}/status", headers=_h(world["b"]))).json()
    assert st_b["requested_by_me"] is False and "requested_by" not in st_b
    st_admin = (await client.get(f"/v1/books/{job['book_id']}/status",
                                 headers=_h(world["admin"]))).json()
    assert st_admin["requested_by"] == str(world["a"])

    # 占位行不出现在阅读器书单里（ListBooks 只列 ready/partial）
    lst = (await client.post("/mcp/ListBooks", json={}, headers=_h(world["a"]))).json()
    assert job["book_id"] not in {x["book_id"] for x in lst["books"]}

    r404 = await client.get("/v1/books/bkj_doesnotexist/status", headers=_h(world["a"]))
    assert r404.status_code == 404


@pytest.mark.asyncio
async def test_same_textbook_in_flight_is_deduplicated(world, client):
    first = (await client.post("/v1/books/compile", json={"textbook_id": world["tb"]},
                               headers=_h(world["a"]))).json()
    second = await client.post("/v1/books/compile", json={"textbook_id": world["tb"]},
                               headers=_h(world["b"]))
    assert second.status_code == 202
    assert second.json()["book_id"] == first["book_id"]
    assert second.json()["deduplicated"] is True
    assert world["enqueued"] == [first["book_id"]]


@pytest.mark.asyncio
async def test_per_user_daily_limit_and_admin_exempt(world, client, monkeypatch):
    monkeypatch.setenv("MNEME_BOOK_COMPILE_DAILY_LIMIT", "1")
    r1 = await client.post("/v1/books/compile", json={"textbook_id": world["tb"]},
                           headers=_h(world["a"]))
    assert r1.status_code == 202
    await _set_status(r1.json()["book_id"], "error")  # 失败也计数
    r2 = await client.post("/v1/books/compile", json={"textbook_id": world["tb"]},
                           headers=_h(world["a"]))
    assert r2.status_code == 429
    # 另一个学生不受 A 的额度影响
    rb = await client.post("/v1/books/compile", json={"textbook_id": world["tb"]},
                           headers=_h(world["b"]))
    assert rb.status_code == 202
    await _set_status(rb.json()["book_id"], "ready")
    # admin 不受 per-user 限额
    for _ in range(2):
        ra = await client.post("/v1/books/compile", json={"textbook_id": world["tb"]},
                               headers=_h(world["admin"]))
        assert ra.status_code == 202, ra.text
        await _set_status(ra.json()["book_id"], "ready")


@pytest.mark.asyncio
async def test_global_daily_cost_cap(world, client, monkeypatch):
    monkeypatch.setenv("MNEME_BOOK_COMPILE_MAX_USD", "1.0")
    monkeypatch.setenv("MNEME_BOOK_COMPILE_DAILY_USD", "0.5")
    r = await client.post("/v1/books/compile", json={"textbook_id": world["tb"]},
                          headers=_h(world["admin"]))
    assert r.status_code == 429
    assert world["enqueued"] == []


@pytest.mark.asyncio
async def test_enqueue_failure_marks_error_and_503(world, client, monkeypatch):
    def boom(book_id):
        raise ConnectionError("broker down")

    monkeypatch.setattr(svc, "enqueue_compile", boom)
    r = await client.post("/v1/books/compile", json={"textbook_id": world["tb"]},
                          headers=_h(world["a"]))
    assert r.status_code == 503
    async with SessionLocal() as db:
        row = (await db.execute(
            text("SELECT status, error FROM books WHERE textbook_id=:t"), {"t": world["tb"]}
        )).fetchone()
    assert row.status == "error" and "投递失败" in row.error


@pytest.mark.asyncio
async def test_compilable_textbooks_lists_only_clustered(world, client):
    r = await client.get("/v1/books/compile/textbooks", headers=_h(world["a"]))
    assert r.status_code == 200
    ids = {t["textbook_id"] for t in r.json()["textbooks"]}
    assert world["tb"] in ids and world["tb_empty"] not in ids
    assert r.json()["daily_limit"] == 3


# ---------------- 任务体 ----------------

def _fake_caller(calls: list | None = None):
    content = json.dumps({"title": "入口测试书", "description": "d", "scope": "s",
                          "target_level": "G1", "estimated_chapters": 1, "rationale": "r"},
                         ensure_ascii=False)

    async def call(*, messages, system=None, max_tokens=800):
        if calls is not None:
            calls.append(1)
        return {"content": content, "usage": {"input_tokens": 100, "output_tokens": 50}}

    return call


async def _queue(world) -> str:
    async with SessionLocal() as db:
        job = await svc.create_compile_job(db, requested_by=str(world["a"]),
                                           textbook_id=world["tb"], is_admin=False)
    return job["book_id"]


@pytest.mark.asyncio
async def test_run_compile_job_adopts_book_under_stable_id(world, tmp_path: Path):
    book_id = await _queue(world)
    res = await svc.run_compile_job(book_id, session_factory=SessionLocal,
                                    caller=_fake_caller(), out_root=tmp_path)
    assert res["status"] in ("ready", "partial"), res
    async with SessionLocal() as db:
        rows = (await db.execute(text("SELECT id, status, title, cost_usd, requested_by, "
                                      "report_path FROM books WHERE textbook_id=:t"),
                                 {"t": world["tb"]})).fetchall()
        assert [r.id for r in rows] == [book_id]  # omodul 生成的那一行已并入占位行
        row = rows[0]
        assert row.status == res["status"] and row.title == "入口测试书"
        assert row.cost_usd > 0 and row.requested_by == str(world["a"])
        assert row.report_path and Path(row.report_path).exists()
        n_ch = (await db.execute(text("SELECT count(*) FROM book_chapters WHERE book_id=:b"),
                                 {"b": book_id})).scalar_one()
        assert n_ch == res["n_chapters"] > 0
        st = await svc.get_compile_status(db, book_id)
    assert st is not None and st["n_blocks"] > 0 and st["stale"] is False

    # 幂等：重投不会二次编译
    calls: list = []
    again = await svc.run_compile_job(book_id, session_factory=SessionLocal,
                                      caller=_fake_caller(calls), out_root=tmp_path)
    assert again["status"] == "skipped" and calls == []


@pytest.mark.asyncio
async def test_stale_compiling_row_is_reclaimed_on_redelivery(world, tmp_path: Path):
    """worker 在编译中途被重启：行卡在 compiling。重投时超过 STALE 的残留可重新认领，
    没超过的（可能真在跑）不碰。"""
    book_id = await _queue(world)
    async with SessionLocal() as db:
        await db.execute(text("UPDATE books SET status='compiling', updated_at=now() WHERE id=:id"),
                         {"id": book_id})
        await db.commit()
    res = await svc.run_compile_job(book_id, session_factory=SessionLocal,
                                    caller=_fake_caller(), out_root=tmp_path)
    assert res["status"] == "skipped"
    async with SessionLocal() as db:
        await db.execute(
            text("UPDATE books SET updated_at = now() - interval '61 minutes' WHERE id=:id"),
            {"id": book_id})
        await db.commit()
        st = await svc.get_compile_status(db, book_id)
    assert st is not None and st["stale"] is True
    res = await svc.run_compile_job(book_id, session_factory=SessionLocal,
                                    caller=_fake_caller(), out_root=tmp_path)
    assert res["status"] in ("ready", "partial"), res


@pytest.mark.asyncio
async def test_run_compile_job_cost_cap_marks_error(world, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MNEME_BOOK_COMPILE_MAX_USD", "0.000001")  # 第一次调用之后即超
    book_id = await _queue(world)
    res = await svc.run_compile_job(book_id, session_factory=SessionLocal,
                                    caller=_fake_caller(), out_root=tmp_path)
    assert res["status"] == "error"
    async with SessionLocal() as db:
        st = await svc.get_compile_status(db, book_id)
    assert st is not None and st["status"] == "error" and st["error"]


@pytest.mark.asyncio
async def test_run_compile_job_caller_crash_marks_error(world, tmp_path: Path):
    """provider 全挂：omodul 各生成器会回退静态模板仍标 ready，入口层必须把它判成
    error，不能让一本纯模板书冒充正常成书出现在书单里。"""

    async def broken(*, messages, system=None, max_tokens=800):
        raise RuntimeError("provider exploded")

    book_id = await _queue(world)
    res = await svc.run_compile_job(book_id, session_factory=SessionLocal,
                                    caller=broken, out_root=tmp_path)
    assert res["status"] == "error"
    async with SessionLocal() as db:
        st = await svc.get_compile_status(db, book_id)
    assert st is not None and st["status"] == "error" and "失败" in st["error"]


@pytest.mark.asyncio
async def test_run_compile_job_partial_llm_failure_downgrades(world, tmp_path: Path):
    good = _fake_caller()
    n = {"i": 0}

    async def flaky(*, messages, system=None, max_tokens=800):
        n["i"] += 1
        if n["i"] > 2:  # ideation/spine 成功，之后的生成失败 → 回退模板
            raise RuntimeError("flaky")
        return await good(messages=messages, system=system, max_tokens=max_tokens)

    book_id = await _queue(world)
    res = await svc.run_compile_job(book_id, session_factory=SessionLocal,
                                    caller=flaky, out_root=tmp_path)
    assert res["status"] == "partial", res
    assert res["llm_calls_failed"] > 0 and res["llm_calls_ok"] == 2


@pytest.mark.asyncio
async def test_run_compile_job_empty_content_is_not_ready(world, tmp_path: Path):
    """推理模型额度不足时 HTTP 成功但 content 为空：omodul 回退模板仍标 ready，
    入口层必须判 error（2026-10-11 生产实测出现过）。"""

    async def empty(*, messages, system=None, max_tokens=800):
        return {"content": "", "usage": {"input_tokens": 10, "output_tokens": 600}}

    book_id = await _queue(world)
    res = await svc.run_compile_job(book_id, session_factory=SessionLocal,
                                    caller=empty, out_root=tmp_path)
    assert res["status"] == "error", res
    async with SessionLocal() as db:
        st = await svc.get_compile_status(db, book_id)
    assert st is not None and st["status"] == "error" and "空内容" in st["error"]


def test_budget_caller_lifts_max_tokens_and_passes_extras():
    seen: dict = {}

    async def raw(*, messages, system=None, max_tokens=800, enable_thinking=None):
        seen.update(max_tokens=max_tokens, enable_thinking=enable_thinking)
        return {"content": "ok", "usage": {"input_tokens": 1, "output_tokens": 1}}

    async def go():
        b = svc.BudgetCaller(raw, cap_usd=1.0, model="m", min_tokens=6000,
                             extra_kwargs={"enable_thinking": False})
        await b(messages=[], max_tokens=150)
        assert seen == {"max_tokens": 6000, "enable_thinking": False}
        assert b.ok_calls == 1 and b.failed_calls == 0

    asyncio.run(go())


def test_budget_caller_stops_after_cap():
    async def raw(*, messages, system=None, max_tokens=800):
        return {"content": "x", "usage": {"input_tokens": 1000, "output_tokens": 1000}}

    async def go():
        b = svc.BudgetCaller(raw, cap_usd=0.01, model="claude-sonnet-4-6")
        await b(messages=[])  # 0.018 > cap after this call
        with pytest.raises(svc.BookBudgetExceeded):
            await b(messages=[])
        assert b.exceeded

    asyncio.run(go())


def test_celery_task_registered():
    from tasks.celery_app import celery_app

    assert "tasks.book_tasks" in celery_app.conf.include
    import tasks.book_tasks  # noqa: F401

    assert "tasks.compile_book" in celery_app.tasks


# ---------------- CLI ----------------

def test_cli_book_commands_hit_entry_endpoints():
    from cli.mneme_cli import MnemeClient

    seen: list[tuple[str, str, bytes]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path, req.content))
        if req.url.path.endswith("/status"):
            return httpx.Response(200, json={"book_id": "bkj_1", "status": "ready"})
        if req.url.path.endswith("/textbooks"):
            return httpx.Response(200, json={"textbooks": []})
        return httpx.Response(202, json={"book_id": "bkj_1", "status": "queued"})

    c = MnemeClient(base_url="http://mock", token="t", transport=httpx.MockTransport(handler))
    assert c.book_compile("TB1")["status"] == "queued"
    assert c.book_status("bkj_1")["status"] == "ready"
    assert c.book_textbooks() == {"textbooks": []}
    assert seen[0][:2] == ("POST", "/v1/books/compile")
    assert json.loads(seen[0][2]) == {"textbook_id": "TB1"}
    assert seen[1][:2] == ("GET", "/v1/books/bkj_1/status")
    assert seen[2][:2] == ("GET", "/v1/books/compile/textbooks")
