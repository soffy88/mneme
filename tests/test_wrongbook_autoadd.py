"""错题自动进错题本（practice / kc_review / solver check，按题干去重）+ 汇总/反馈接口。"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from obase.auth import create_access_token
from obase.db import SessionLocal
from services.main import app
from services.models import QuestionRecord, User, UserRole, WrongQuestion


def _h(u: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(u)})}"}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wqs(student_id: uuid.UUID) -> list[WrongQuestion]:
    async with SessionLocal() as db:
        return list(
            (await db.execute(select(WrongQuestion).where(WrongQuestion.student_id == student_id))).scalars().all()
        )


async def _records(student_id: uuid.UUID, source: str) -> list[QuestionRecord]:
    async with SessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(QuestionRecord)
                    .where(QuestionRecord.student_id == student_id, QuestionRecord.source == source)
                    .order_by(QuestionRecord.created_at)
                )
            ).scalars().all()
        )


@pytest.fixture
async def student():
    a = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=a, phone=f"177{str(a.int)[:8]}", role=UserRole.student, grade="初二"))
        await db.commit()
    yield a
    from services.purge_service import _STUDENT_TABLES, _table_exists

    async with SessionLocal() as db:
        for table, col in _STUDENT_TABLES:
            if await _table_exists(db, table):
                await db.execute(text(f"DELETE FROM {table} WHERE {col}::text = :i"), {"i": str(a)})
        await db.execute(text("DELETE FROM users WHERE id::text = :i"), {"i": str(a)})
        await db.commit()


@pytest.mark.asyncio
async def test_practice_wrong_answer_dedups_in_wrongbook(student):
    a = student
    bank_id = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(WrongQuestion(id=bank_id, student_id=None, subject="math", question_text="AA-BANK 2+2=? 选 B",
                             correct_answer="B", knowledge_points={"aa-kc": "加法"}))
        await db.commit()
    try:
        async with _client() as c:
            for _ in range(2):
                r = await c.post("/v1/practice/submit", json={"student_id": str(a), "question_id": str(bank_id),
                                                              "ku_id": "aa-kc", "student_answer": "C"}, headers=_h(a))
                assert r.status_code == 200, r.text
                assert r.json()["is_correct"] is False and r.json()["wrong_question_id"]
        wqs = await _wqs(a)
        assert len(wqs) == 1, "同一题答错两次只进错题本一次"
        wq = wqs[0]
        assert wq.source == "practice" and wq.knowledge_points == {"aa-kc": "加法"} and wq.student_answer == "C"
        recs = await _records(a, "practice")
        assert len(recs) == 2 and {r.wrong_question_id for r in recs} == {wq.id}
        # 进了错题本 → 今天的 10 分钟复习里就有它
        async with _client() as c:
            today = (await c.get("/v1/review/today", headers=_h(a))).json()
        assert any(it["item_id"] == str(wq.id) for it in today["items"])
    finally:
        async with SessionLocal() as db:
            await db.execute(text("DELETE FROM wrong_questions WHERE id = :i"), {"i": bank_id})
            await db.commit()


@pytest.mark.asyncio
async def test_kc_review_wrong_answer_requeues_original(student, monkeypatch):
    a = student
    import services.cognitive_service as cs
    import services.review_service as rs

    async def fake_answer(db, student_id, kc_id):
        return "B"

    async def fake_probe(db, student_id, kc_id, now=None):
        return "review", None

    async def fake_pi(*args, **kwargs):
        return {}

    monkeypatch.setattr(rs, "_answer_for_review", fake_answer)
    monkeypatch.setattr(rs, "_probe_context", fake_probe)
    monkeypatch.setattr(cs, "process_interaction", fake_pi)
    orig_id = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(WrongQuestion(id=orig_id, student_id=a, subject="math", question_text="AA 3×4=? A.7 B.12 C.13", correct_answer="B",
                             knowledge_points={"aa-kc2": "aa-kc2"}, review_correct_streak=2))
        await db.commit()
    async with _client() as c:
        r = await c.post(f"/v1/review/submit/{a}", json={"ku_id": "aa-kc2", "answer": "C"}, headers=_h(a))
        assert r.status_code == 200, r.text
        assert r.json()["verdict"] == "wrong"
    recs = await _records(a, "kc_review")
    assert len(recs) == 1 and recs[0].is_correct is False
    assert recs[0].question_text == "AA 3×4=? A.7 B.12 C.13" and recs[0].wrong_question_id == orig_id
    wqs = await _wqs(a)
    assert len(wqs) == 1 and wqs[0].review_correct_streak == 0 and wqs[0].fsrs_due is not None


@pytest.mark.asyncio
async def test_solver_check_wrong_answer_goes_to_wrongbook(student):
    a = student
    body = {"text": "He go to school", "accepted": ["He goes to school"], "type": "fill",
            "context": "AA 用 go 的正确形式填空：He ___ to school every day."}
    async with _client() as c:
        for _ in range(2):
            r = await c.post("/v1/english/check", json=body, headers=_h(a))
            assert r.status_code == 200, r.text
    recs = await _records(a, "solver")
    assert len(recs) == 2 and all(r.is_correct is False for r in recs)
    wqs = await _wqs(a)
    assert len(wqs) == 1 and wqs[0].source == "solver" and wqs[0].question_text.startswith("AA 用 go")


@pytest.mark.asyncio
async def test_summary_report_and_finish_fields(student):
    a = student
    async with _client() as c:
        ask = (await c.post("/v1/questions/ask", data={"text": "解方程：3x + 5 = 20"}, headers=_h(a))).json()
        s = (await c.post(f"/v1/questions/ask/{ask['ask_id']}/solve", json={"text": ask["text"]}, headers=_h(a))).json()
        assert s["solver"] == "kernel"
        rep = await c.post(f"/v1/questions/ask/{ask['ask_id']}/report", json={"reason": "答案错了", "comment": "AA"}, headers=_h(a))
        assert rep.status_code == 200 and rep.json() == {"ok": True}
        bad = await c.post(f"/v1/questions/ask/{ask['ask_id']}/report", json={"reason": "乱写"}, headers=_h(a))
        assert bad.status_code == 422
        summ = (await c.get("/v1/questions/summary?days=7", headers=_h(a))).json()
        assert len(summ["days"]) == 7 and summ["days"][-1]["count"] >= 1
        assert set(summ["days"][-1]) >= {"date", "count", "graded", "correct", "wrong", "accuracy", "top_wrong_kcs"}
        fin = (await c.post("/v1/review/today/finish", json={"answered": 0, "correct": 0}, headers=_h(a))).json()
        assert {"due_tomorrow", "today_answered", "today_correct", "today_minutes", "streak"} <= set(fin)
    async with SessionLocal() as db:
        rec = await db.get(QuestionRecord, uuid.UUID(ask["ask_id"]))
        assert rec is not None and rec.meta["reports"][0]["reason"] == "答案错了"
        assert rec.meta["reports"][0]["kernel"] == s["kernel"]
