"""Notebook + Co-Writer（DeepTutor 对标，学习者自有、儿童安全）。

覆盖：
① /v1/notebooks CRUD：本人 200/201；他人笔记本 403；不存在 404；家长 403；匿名 401；
   同名 409；非法 source_type 422；/save 一键入口按名字建本
② purge：软删用户的 notebooks / notebook_records / cowriter_requests 被物理清除；
   清单顺序 notebook_records 先于 notebooks
③ Co-Writer 不代写规则：代写请求 / 只贴题目 / 太短 → 422，且不调用 LLM
④ Co-Writer 正常建议：diff hunks 全接受 = 修改稿、全拒绝 = 原文；输出按输入长度封顶
⑤ LLM 失败（空 content / 异常）→ 502 并记 failed；无 caller → 503；每日限额 → 429；家长 403
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from obase.auth import create_access_token
from obase.db import SessionLocal
from services import cowriter_service as cw
from services.main import app
from services.models import ParentStudent, User, UserRole

SAMPLE_ZH = "今天我和爸爸去公元放风筝，风很大风筝飞的很高，我特别开心，回家路上还买了冰淇淋。"
SAMPLE_EN = "I goes to the park yesterday with my friend and we plays football for two hours. It was fun."


def _h(user_id: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}


async def _cleanup(ids: list[uuid.UUID]) -> None:
    async with SessionLocal() as db:
        for tbl in ("notebook_records", "notebooks", "cowriter_requests"):
            await db.execute(text(f"DELETE FROM {tbl} WHERE student_id = ANY(:ids)"), {"ids": ids})  # noqa: S608
        await db.execute(
            text("DELETE FROM parent_student WHERE student_id = ANY(:ids) OR parent_id = ANY(:ids)"),
            {"ids": ids},
        )
        await db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": ids})
        await db.commit()


@pytest.fixture
async def actors():
    a, b, p = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=a, phone=f"171{str(a.int)[:8]}", role=UserRole.student, name="NA"))
        db.add(User(id=b, phone=f"172{str(b.int)[:8]}", role=UserRole.student, name="NB"))
        db.add(User(id=p, phone=f"173{str(p.int)[:8]}", role=UserRole.parent, name="NP"))
        await db.flush()
        db.add(ParentStudent(parent_id=p, student_id=a))
        await db.commit()
    yield {"a": a, "b": b, "p": p}
    await _cleanup([a, b, p])


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


# ── ① Notebook CRUD + ownership ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_notebook_crud_and_ownership(actors, client):
    a, b, p = actors["a"], actors["b"], actors["p"]

    r = await client.post("/v1/notebooks", json={"name": "数学错因"}, headers=_h(a))
    assert r.status_code == 201, r.text
    nb_id = r.json()["id"]

    r = await client.post("/v1/notebooks", json={"name": "数学错因"}, headers=_h(a))
    assert r.status_code == 409

    r = await client.post(
        f"/v1/notebooks/{nb_id}/records",
        json={
            "source_type": "book_block",
            "source_id": "blk_123",
            "kc_id": "math.fraction.add",
            "title": "分数加法",
            "content": "异分母分数相加先通分。",
            "metadata": {"book_id": "bk_x"},
        },
        headers=_h(a),
    )
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["source_type"] == "book_block" and rec["kc_id"] == "math.fraction.add"
    assert rec["source_id"] == "blk_123" and rec["metadata"] == {"book_id": "bk_x"}

    r = await client.post(
        f"/v1/notebooks/{nb_id}/records", json={"source_type": "homework", "content": "x"}, headers=_h(a)
    )
    assert r.status_code == 422

    r = await client.get("/v1/notebooks", headers=_h(a))
    assert r.status_code == 200
    assert [(n["id"], n["record_count"]) for n in r.json()["notebooks"]] == [(nb_id, 1)]

    r = await client.get(f"/v1/notebooks/{nb_id}", headers=_h(a))
    assert r.status_code == 200 and [x["id"] for x in r.json()["records"]] == [rec["id"]]

    # 他人：读/写/改/删 一律 403；列表只看到自己的（空）
    assert (await client.get(f"/v1/notebooks/{nb_id}", headers=_h(b))).status_code == 403
    assert (
        await client.post(
            f"/v1/notebooks/{nb_id}/records", json={"source_type": "free_text", "content": "hi"}, headers=_h(b)
        )
    ).status_code == 403
    assert (
        await client.patch(f"/v1/notebooks/{nb_id}/records/{rec['id']}", json={"content": "x"}, headers=_h(b))
    ).status_code == 403
    assert (await client.delete(f"/v1/notebooks/{nb_id}/records/{rec['id']}", headers=_h(b))).status_code == 403
    assert (await client.delete(f"/v1/notebooks/{nb_id}", headers=_h(b))).status_code == 403
    assert (await client.get("/v1/notebooks", headers=_h(b))).json()["notebooks"] == []

    # 绑定家长也不能读（现有授权模型没有"家长读孩子笔记"）
    assert (await client.get("/v1/notebooks", headers=_h(p))).status_code == 403
    assert (await client.get(f"/v1/notebooks/{nb_id}", headers=_h(p))).status_code == 403
    # 匿名 401；不存在 404
    assert (await client.get("/v1/notebooks")).status_code == 401
    assert (await client.get("/v1/notebooks/nb_nope", headers=_h(a))).status_code == 404

    # 本人改、删
    r = await client.patch(f"/v1/notebooks/{nb_id}/records/{rec['id']}", json={"content": "先通分再相加。"}, headers=_h(a))
    assert r.status_code == 200 and r.json()["content"] == "先通分再相加。"
    r = await client.patch(f"/v1/notebooks/{nb_id}", json={"name": "分数"}, headers=_h(a))
    assert r.status_code == 200 and r.json()["name"] == "分数"
    assert (await client.delete(f"/v1/notebooks/{nb_id}/records/{rec['id']}", headers=_h(a))).status_code == 200
    assert (await client.get(f"/v1/notebooks/{nb_id}", headers=_h(a))).json()["records"] == []
    assert (await client.delete(f"/v1/notebooks/{nb_id}", headers=_h(a))).status_code == 200
    assert (await client.get(f"/v1/notebooks/{nb_id}", headers=_h(a))).status_code == 404


@pytest.mark.asyncio
async def test_save_endpoint_creates_named_notebook_and_reuses_it(actors, client):
    a, b = actors["a"], actors["b"]
    body = {"source_type": "chat", "content": "光合作用把光能变成化学能。", "kc_id": "bio.photosynthesis"}
    r1 = await client.post("/v1/notebooks/save", json=body, headers=_h(a))
    assert r1.status_code == 201, r1.text
    r2 = await client.post("/v1/notebooks/save", json={**body, "content": "第二条"}, headers=_h(a))
    assert r2.status_code == 201
    assert r1.json()["notebook_id"] == r2.json()["notebook_id"]
    nb = (await client.get(f"/v1/notebooks/{r1.json()['notebook_id']}", headers=_h(a))).json()
    assert nb["name"] == "我的笔记" and nb["record_count"] == 2
    # 拿别人的 notebook_id 存 → 403
    r = await client.post("/v1/notebooks/save", json={**body, "notebook_id": r1.json()["notebook_id"]}, headers=_h(b))
    assert r.status_code == 403


# ── ② purge ────────────────────────────────────────────────────────────────


def test_new_tables_are_in_purge_inventory_in_fk_order():
    from services.purge_service import _STUDENT_TABLES

    names = [t for t, _ in _STUDENT_TABLES]
    for tbl in ("notebook_records", "notebooks", "cowriter_requests"):
        assert (tbl, "student_id") in _STUDENT_TABLES
    assert names.index("notebook_records") < names.index("notebooks")


@pytest.mark.asyncio
async def test_purge_removes_notebooks_records_and_cowriter_ledger(monkeypatch):
    from services import notebook_service as nbs
    from services.models import CowriterRequest
    from services.purge_service import purge_deleted_users

    async def no_storage_cleanup():
        return []

    monkeypatch.setattr("services.purge_service._delete_textbook_files_blobs", no_storage_cleanup)
    monkeypatch.setattr("services.purge_service._delete_media_files_blobs", no_storage_cleanup)

    sid = uuid.uuid4()
    try:
        async with SessionLocal() as db:
            db.add(
                User(
                    id=sid,
                    phone=f"174{str(sid.int)[:8]}",
                    role=UserRole.student,
                    deleted_at=datetime.now(UTC) - timedelta(days=40),
                )
            )
            await db.flush()
            out = await nbs.save_to_notebook(
                db, sid, notebook_id=None, notebook_name="作文", source_type="cowriter", content="草稿"
            )
            db.add(CowriterRequest(student_id=sid, action="grammar", status="ok", input_chars=10, output_chars=10))
            await db.commit()
            assert out["notebook_id"].startswith("nb_")

        async with SessionLocal() as db:
            result = await purge_deleted_users(db, grace_days=30)
            await db.commit()
        assert str(sid) in result["ids"]
        async with SessionLocal() as db:
            for tbl in ("notebook_records", "notebooks", "cowriter_requests"):
                n = (
                    await db.execute(text(f"SELECT count(*) FROM {tbl} WHERE student_id = :s"), {"s": sid})  # noqa: S608
                ).scalar_one()
                assert n == 0, tbl
    finally:
        await _cleanup([sid])


# ── ③ 不代写规则（纯函数）───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text_", "instruction", "code"),
    [
        ("帮我写一篇作文，题目是我的妈妈", None, "ghostwriting"),
        ("请给我写一篇读后感", None, "ghostwriting"),
        ("题目：我的暑假。要求：不少于600字", None, "prompt_only"),
        ("以“成长”为题，写一篇不少于 500 字的记叙文。", None, "ghostwriting"),
        ("Write an essay about my summer vacation in at least 300 words.", None, "ghostwriting"),
        ("Topic: My best friend. 200 words.", None, "prompt_only"),
        (SAMPLE_ZH, "直接帮我写完整篇", "ghostwriting"),
        (SAMPLE_EN, "write it for me", "ghostwriting"),
        (SAMPLE_EN, "please do my homework", "ghostwriting"),
        ("今天天气很好", None, "too_short"),
        ("I like cats.", None, "too_short"),
    ],
)
def test_refusal_rules(text_, instruction, code):
    err = cw.check_request("rewrite", text_, instruction)
    assert err is not None and err.code == code and err.status_code == 422


@pytest.mark.parametrize("text_", [SAMPLE_ZH, SAMPLE_EN])
def test_learner_own_text_is_allowed(text_):
    for action in cw.ACTIONS:
        assert cw.check_request(action, text_, "让句子更生动一点") is None


def test_long_learner_text_mentioning_assignment_is_not_misjudged():
    own = (
        "老师让我们写一篇关于秋天的作文。我想先写校园里的银杏树，"
        "每到十月，金黄的叶子落满操场，同学们捡起叶子做书签。"
        "放学的时候，夕阳照在树叶上，整条路都亮了起来，我觉得秋天是一个温暖的季节。"
        "周末我和妈妈去公园，看到湖边的枫叶也红了，风一吹，叶子像蝴蝶一样飞舞。"
    )
    assert cw.count_units(own) >= 80
    assert cw.check_request("grammar", own, None) is None


def test_diff_roundtrip_and_cap():
    revised = "I went to the park yesterday with my friend, and we played football for two hours. It was fun."
    d = cw.build_diff(SAMPLE_EN, revised, "en")
    assert d["hunks"]
    assert cw.apply_hunks(SAMPLE_EN, d["hunks"], [h["id"] for h in d["hunks"]]) == revised
    assert cw.apply_hunks(SAMPLE_EN, d["hunks"], []) == SAMPLE_EN
    zh_rev = "今天我和爸爸去公园放风筝，风很大，风筝飞得很高，我特别开心，回家路上还买了冰淇淋。"
    d = cw.build_diff(SAMPLE_ZH, zh_rev, "zh")
    assert cw.apply_hunks(SAMPLE_ZH, d["hunks"], [h["id"] for h in d["hunks"]]) == zh_rev
    for action in cw.ACTIONS:
        assert cw.output_char_cap(action, SAMPLE_ZH) <= int(len(SAMPLE_ZH) * 1.6) + cw.LENGTH_SLACK_CHARS


# ── ④⑤ HTTP suggest ────────────────────────────────────────────────────────


class FakeCaller:
    def __init__(self, content: str = "", exc: Exception | None = None):
        self.content = content
        self.exc = exc
        self.calls: list[dict] = []

    async def __call__(self, *, messages, system=None, max_tokens=800, **kw):
        self.calls.append({"messages": messages, "system": system, "max_tokens": max_tokens, **kw})
        if self.exc:
            raise self.exc
        return {"content": self.content, "usage": {}}


def _use(monkeypatch, caller):
    monkeypatch.setattr("services.providers.setup.get_optional_text_caller", lambda: caller)


async def _ledger(sid: uuid.UUID) -> list[str]:
    async with SessionLocal() as db:
        rows = await db.execute(
            text("SELECT status FROM cowriter_requests WHERE student_id = :s ORDER BY created_at"), {"s": sid}
        )
        return [r[0] for r in rows]


@pytest.mark.asyncio
async def test_suggest_refuses_ghostwriting_without_calling_llm(actors, client, monkeypatch):
    fake = FakeCaller('{"revised": "一整篇作文……", "notes": []}')
    _use(monkeypatch, fake)
    r = await client.post(
        "/v1/cowriter/suggest", json={"action": "expand", "text": "帮我写一篇作文：我的妈妈"}, headers=_h(actors["a"])
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "ghostwriting"
    assert fake.calls == []
    assert await _ledger(actors["a"]) == ["refused"]


@pytest.mark.asyncio
async def test_suggest_returns_diff_and_caps_length(actors, client, monkeypatch):
    revised = "今天我和爸爸去公园放风筝，风很大，风筝飞得很高，我特别开心，回家路上还买了冰淇淋。"
    fake = FakeCaller('{"revised": "%s", "notes": ["“公元”应为“公园”", "“飞的”应为“飞得”"]}' % revised)
    _use(monkeypatch, fake)
    r = await client.post("/v1/cowriter/suggest", json={"action": "grammar", "text": SAMPLE_ZH}, headers=_h(actors["a"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggestion"] == revised and body["truncated"] is False
    assert cw.apply_hunks(body["original"], body["hunks"], [h["id"] for h in body["hunks"]]) == revised
    assert len(body["notes"]) == 2
    assert fake.calls and fake.calls[0]["max_tokens"] >= 256
    assert body["usage"]["used_today"] == 1

    # 模型试图把三句话扩成长文 → 按输入长度封顶截断
    long_out = "风筝越飞越高。" * 200
    _use(monkeypatch, FakeCaller('{"revised": "%s", "notes": []}' % long_out))
    r = await client.post("/v1/cowriter/suggest", json={"action": "expand", "text": SAMPLE_ZH}, headers=_h(actors["a"]))
    assert r.status_code == 200
    body = r.json()
    assert body["truncated"] is True
    assert len(body["suggestion"]) <= cw.output_char_cap("expand", SAMPLE_ZH)
    assert await _ledger(actors["a"]) == ["ok", "ok"]


@pytest.mark.asyncio
async def test_suggest_llm_failure_is_graceful(actors, client, monkeypatch):
    a = actors["a"]
    _use(monkeypatch, FakeCaller(""))
    r = await client.post("/v1/cowriter/suggest", json={"action": "rewrite", "text": SAMPLE_EN}, headers=_h(a))
    assert r.status_code == 502 and r.json()["detail"]["code"] == "llm_failed"
    _use(monkeypatch, FakeCaller(exc=RuntimeError("provider down")))
    r = await client.post("/v1/cowriter/suggest", json={"action": "rewrite", "text": SAMPLE_EN}, headers=_h(a))
    assert r.status_code == 502
    _use(monkeypatch, None)
    r = await client.post("/v1/cowriter/suggest", json={"action": "rewrite", "text": SAMPLE_EN}, headers=_h(a))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "llm_unavailable"
    assert await _ledger(a) == ["failed", "failed"]


@pytest.mark.asyncio
async def test_suggest_daily_limit_and_parent_forbidden(actors, client, monkeypatch):
    monkeypatch.setenv("MNEME_COWRITER_DAILY_LIMIT", "1")
    _use(monkeypatch, FakeCaller('{"revised": "I went to the park yesterday with my friend.", "notes": []}'))
    a = actors["a"]
    r = await client.post("/v1/cowriter/suggest", json={"action": "grammar", "text": SAMPLE_EN}, headers=_h(a))
    assert r.status_code == 200
    r = await client.post("/v1/cowriter/suggest", json={"action": "grammar", "text": SAMPLE_EN}, headers=_h(a))
    assert r.status_code == 429 and r.json()["detail"]["code"] == "daily_limit"
    lim = (await client.get("/v1/cowriter/limits", headers=_h(a))).json()
    assert lim["used_today"] == 1 and lim["daily_limit"] == 1
    assert (
        await client.post("/v1/cowriter/suggest", json={"action": "grammar", "text": SAMPLE_EN}, headers=_h(actors["p"]))
    ).status_code == 403
    assert (await client.post("/v1/cowriter/suggest", json={"action": "grammar", "text": SAMPLE_EN})).status_code == 401
