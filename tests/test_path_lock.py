"""服务端掌握路径锁（/mcp/RequestQuestion，env MNEME_PATH_LOCK，默认开）。

真实测试库（学生/错题/kc_mastery/pending/收藏自建自清）；路径视图用替身注入
（tool_get_mastery_path 本身的派生规则见 tests/test_mastery_path_view.py），出题本身
用替身（不触 LLM）。覆盖：locked 拒绝 + 每一种放行路径 + fail-open + 红线。
"""

from __future__ import annotations

import ast
import logging
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text

import services.mcp_router as mr
from obase.auth import create_access_token
from obase.db import SessionLocal
from services import path_lock_service as pls
from services.main import app
from services.models import KCMastery, ParentStudent, User, UserRole, WrongQuestion

KCS = ["pl-a", "pl-b", "pl-c", "pl-d"]


def _view(states: dict[str, str], *, review_due=(), n_obs=None, status="completed"):
    n_obs = n_obs or {}
    nodes = [
        {
            "kc_id": k,
            "name": f"名-{k}",
            "kc_type": "procedure",
            "state": st,
            "n_obs": n_obs.get(k, 0),
            "review_due": k in review_due,
        }
        for k, st in states.items()
    ]
    cur = next((n["kc_id"] for n in nodes if n["state"] == "current"), None)
    return {"textbook_id": "tb", "status": status, "nodes": nodes, "current_kc_id": cur}


DEFAULT = {"pl-a": "mastered", "pl-b": "current", "pl-c": "locked", "pl-d": "locked"}


@pytest.fixture
def fake_view(monkeypatch):
    holder: dict = {"view": _view(DEFAULT)}

    async def _gmp(db, student_id, now=None):
        if isinstance(holder["view"], Exception):
            raise holder["view"]
        return holder["view"]

    monkeypatch.setattr(mr, "tool_get_mastery_path", _gmp)
    monkeypatch.delenv("MNEME_PATH_LOCK", raising=False)
    return holder


@pytest.fixture
async def student():
    sid = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=sid, phone=f"175{str(sid.int)[:8]}", role=UserRole.student))
        await db.commit()
    yield sid
    async with SessionLocal() as db:
        p = {"s": str(sid)}
        await db.execute(text("DELETE FROM question_bookmarks WHERE student_id = CAST(:s AS uuid)"), p)
        await db.execute(text("DELETE FROM gate.pending_question WHERE student_id = CAST(:s AS uuid)"), p)
        await db.execute(delete(WrongQuestion).where(WrongQuestion.student_id == sid))
        await db.execute(delete(KCMastery).where(KCMastery.student_id == sid))
        await db.execute(delete(ParentStudent).where(ParentStudent.student_id == sid))
        await db.execute(delete(User).where(User.id == sid))
        await db.commit()


async def _check(sid, kc, **kw):
    async with SessionLocal() as db:
        return await pls.check_path_lock(db, sid, kc, **kw)


@pytest.mark.asyncio
async def test_locked_kc_rejected_with_current(fake_view, student):
    d = await _check(student, "pl-c")
    assert not d.allowed and d.reason == "locked"
    det = d.rejection_detail()
    assert det["code"] == "path_locked"
    assert det["kc_id"] == "pl-c" and det["current_kc_id"] == "pl-b"
    assert det["current_kc_name"] == "名-pl-b" and "名-pl-b" in det["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kc,reason", [("pl-a", "mastered"), ("pl-b", "current"), ("zz-off-path", "not_on_path")])
async def test_mastered_current_and_off_path_allowed(fake_view, student, kc, reason):
    d = await _check(student, kc)
    assert d.allowed and d.reason == reason


@pytest.mark.asyncio
async def test_review_due_and_attempted_locked_nodes_allowed(fake_view, student):
    fake_view["view"] = _view(DEFAULT, review_due={"pl-c"}, n_obs={"pl-d": 2})
    assert (await _check(student, "pl-c")).reason == "review_due"
    assert (await _check(student, "pl-d")).reason == "attempted"


@pytest.mark.asyncio
async def test_fsrs_card_allows_but_bare_mastery_row_does_not(fake_view, student):
    async with SessionLocal() as db:
        for kc, card in (("pl-c", {"due": "2026-10-01T00:00:00+00:00"}), ("pl-d", None)):
            db.add(KCMastery(student_id=student, knowledge_point=kc, p_mastery=0.3, p_init=0.2,
                             p_transit=0.1, p_guess=0.2, p_slip=0.1, fsrs_card_json=card))
        await db.commit()
    assert (await _check(student, "pl-c")).reason == "attempted"
    assert not (await _check(student, "pl-d")).allowed  # 无 FSRS 卡的先验行不算作答过


@pytest.mark.asyncio
async def test_wrong_question_review_allowed(fake_view, student):
    async with SessionLocal() as db:
        db.add(WrongQuestion(student_id=student, question_text="q", correct_answer="SECRET",
                             knowledge_points={"pl-c": 1.0}))
        await db.commit()
    assert (await _check(student, "pl-c")).reason == "wrong_question_review"
    assert not (await _check(student, "pl-d")).allowed


@pytest.mark.asyncio
async def test_bookmark_and_pending_allowed(fake_view, student):
    async with SessionLocal() as db:
        await db.execute(
            text("INSERT INTO question_bookmarks (student_id, source, question_ref, kc_id, prompt) "
                 "VALUES (:s, 'posed', 'q-x', 'pl-c', 'p')"),
            {"s": student},
        )
        await db.execute(
            text("INSERT INTO gate.pending_question (question_id, student_id, kc_id, prompt, expected, qtype) "
                 "VALUES ('q-pl-pend', CAST(:s AS uuid), 'pl-d', 'p', 'SECRET', 'solve')"),
            {"s": str(student)},
        )
        await db.commit()
    assert (await _check(student, "pl-c")).reason == "bookmarked"
    assert (await _check(student, "pl-d")).reason == "pending"


@pytest.mark.asyncio
async def test_env_flag_off_disables(fake_view, student, monkeypatch):
    for v in ("0", "false", "OFF", "no"):
        monkeypatch.setenv("MNEME_PATH_LOCK", v)
        assert (await _check(student, "pl-c")).reason == "disabled"
    monkeypatch.setenv("MNEME_PATH_LOCK", "1")
    assert not (await _check(student, "pl-c")).allowed


@pytest.mark.asyncio
async def test_empty_or_failed_path_allows(fake_view, student):
    fake_view["view"] = _view({}, status="empty")
    assert (await _check(student, "pl-c")).allowed


@pytest.mark.asyncio
async def test_infrastructure_error_fails_open_and_logs(fake_view, student, caplog):
    fake_view["view"] = RuntimeError("db down")
    with caplog.at_level(logging.WARNING, logger="services.path_lock_service"):
        d = await _check(student, "pl-c")
    assert d.allowed and d.reason == "fail_open"
    assert any("path_lock_fail_open" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_quiz_token_scoped_to_student_and_kcs(fake_view, student):
    other = uuid.uuid4()
    tok = pls.issue_quiz_token(student, ["pl-c"], other)
    assert (await _check(student, "pl-c", quiz_token=tok)).reason == "assigned_quiz"
    assert not (await _check(student, "pl-d", quiz_token=tok)).allowed  # 卷外 KC
    assert not (await _check(other, "pl-c", quiz_token=tok)).allowed  # 别的学生
    assert not (await _check(student, "pl-c", quiz_token=tok + "x")).allowed  # 篡改
    # quiz token 不是登录 token（独立派生密钥）
    from obase.auth import decode_access_token

    assert decode_access_token(tok) is None


# ── HTTP 端点 ───────────────────────────────────────────────────────────────


@pytest.fixture
def stub_pose(monkeypatch):
    calls: list = []

    async def _rq(db, student_id, kc_id):
        calls.append(kc_id)
        return {"question_id": "q-stub", "prompt": "1+1=?", "qtype": "solve", "source": "bank"}

    monkeypatch.setattr(mr, "tool_request_question", _rq)
    return calls


def _h(u: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(u)})}"}


@pytest.mark.asyncio
async def test_http_locked_403_current_200(fake_view, student, stub_pose):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/mcp/RequestQuestion", json={"student_id": str(student), "kc_id": "pl-c"}, headers=_h(student))
        assert r.status_code == 403
        d = r.json()["detail"]
        assert d["code"] == "path_locked" and d["current_kc_id"] == "pl-b"
        ok = await c.post("/mcp/RequestQuestion", json={"student_id": str(student), "kc_id": "pl-b"}, headers=_h(student))
        assert ok.status_code == 200 and ok.json()["question_id"] == "q-stub"
        assert "expected" not in ok.json()
    assert stub_pose == ["pl-b"]  # 被拒的请求根本不出题


@pytest.mark.asyncio
async def test_parent_generate_quiz_token_unlocks_student(fake_view, student, stub_pose, monkeypatch):
    parent = uuid.uuid4()

    async def _gq(db, student_id, **kw):
        return {"kc_sequence": ["pl-c"], "size": 1}

    monkeypatch.setattr(mr, "tool_generate_quiz", _gq)
    async with SessionLocal() as db:
        db.add(User(id=parent, phone=f"176{str(parent.int)[:8]}", role=UserRole.parent))
        await db.flush()
        db.add(ParentStudent(parent_id=parent, student_id=student))
        await db.commit()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            own = await c.post("/mcp/GenerateQuiz", json={"student_id": str(student)}, headers=_h(student))
            assert own.status_code == 200 and "quiz_token" not in own.json()  # 自组卷不发
            pq = await c.post("/mcp/GenerateQuiz", json={"student_id": str(student)}, headers=_h(parent))
            tok = pq.json()["quiz_token"]
            r = await c.post("/mcp/RequestQuestion",
                             json={"student_id": str(student), "kc_id": "pl-c", "quiz_token": tok},
                             headers=_h(student))
            assert r.status_code == 200
    finally:
        async with SessionLocal() as db:
            await db.execute(delete(ParentStudent).where(ParentStudent.parent_id == parent))
            await db.execute(delete(User).where(User.id == parent))
            await db.commit()


@pytest.mark.asyncio
async def test_tool_level_callers_not_locked(fake_view, student, monkeypatch):
    """系统/教师侧（tool_generate_quiz、tool_request_question 直调）不经路径锁。"""
    async def _boom(*a, **k):
        raise AssertionError("path lock must not run for tool-level callers")

    monkeypatch.setattr(pls, "check_path_lock", _boom)
    import inspect

    assert "check_path_lock" not in inspect.getsource(mr.tool_request_question)
    assert "check_path_lock" not in inspect.getsource(mr.tool_generate_quiz)


# ── 红线 ────────────────────────────────────────────────────────────────────

_FORBIDDEN = ("mastery_gate", "gate_store", "math_grade", "verdict_guard",
              "cognitive_service", "process_interaction", "answer_match", "providers")


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(a.name for a in node.names)
    return names


def test_path_lock_has_no_gating_or_llm_coupling_and_is_read_only():
    src_path = Path(pls.__file__)
    imported = _imports(src_path)
    hits = [n for n in _FORBIDDEN if any(n in i for i in imported)]
    assert not hits, f"path_lock_service import 了门控写入/判分/LLM 模块 {hits}"
    src = src_path.read_text(encoding="utf-8").upper()
    for kw in ("INSERT ", "UPDATE ", "DELETE "):
        assert kw not in src, f"path_lock_service 出现写语句 {kw.strip()}——必须只读"


def test_gating_functions_unchanged_by_lock():
    import inspect

    from mneme_core.oprim.mastery_gate import is_mastered, next_objective

    for fn in (is_mastered, next_objective):
        params = {p.lower() for p in inspect.signature(fn).parameters}
        assert not any("lock" in p or "bookmark" in p for p in params)
