"""拍照问题目 / 10 分钟错题复习 / 统一做题记录（question_records）。

覆盖：精确求解内核、确定性判分、FSRS 排程与毕业、10 分钟选题、API 全链路（测试库），
以及每个已接线来源（practice / quiz / mcp SubmitAnswer / KC 复习 / 解题工具 / 拍照 / 复习）
都会落一条记录，且记录失败不影响主流程。
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from obase.auth import create_access_token
from obase.db import SessionLocal
from services.main import app
from services.models import QuestionRecord, TimedQuiz, User, UserRole, WrongQuestion


def _h(u: uuid.UUID) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(u)})}"}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _records(student_id: uuid.UUID, source: str | None = None) -> list[QuestionRecord]:
    async with SessionLocal() as db:
        stmt = select(QuestionRecord).where(QuestionRecord.student_id == student_id)
        if source:
            stmt = stmt.where(QuestionRecord.source == source)
        return list((await db.execute(stmt.order_by(QuestionRecord.created_at))).scalars().all())


@pytest.fixture
async def students():
    a, b = uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=a, phone=f"175{str(a.int)[:8]}", role=UserRole.student, grade="初一"))
        db.add(User(id=b, phone=f"176{str(b.int)[:8]}", role=UserRole.student))
        await db.commit()
    yield {"a": a, "b": b}
    from services.purge_service import _STUDENT_TABLES, _table_exists

    # 不走 purge_deleted_users（它会清共享测试库里所有软删用户，碰到别人的 MinIO 对象）；
    # 按 purge 同一张学生表清单只删本测试的两个学生。
    async with SessionLocal() as db:
        ids = [str(a), str(b)]
        for table, col in _STUDENT_TABLES:
            if await _table_exists(db, table):
                await db.execute(text(f"DELETE FROM {table} WHERE {col}::text = ANY(:ids)"), {"ids": ids})
        await db.execute(text("DELETE FROM users WHERE id::text = ANY(:ids)"), {"ids": ids})
        await db.commit()


# ── 纯函数：精确内核 ─────────────────────────────────────────────────────────


def test_kernel_linear_equation_from_ocr_text():
    from services.ask_kernels import solve_math_text

    sol = solve_math_text("1. 解方程：3x+5=20，求× 的值。")
    assert sol is not None and sol.kernel == "algebra.linear_eq"
    assert sol.answer == "x = 5"
    assert any("检验" in s for s in sol.steps)
    assert "x" in sol.hint


def test_kernel_quadratic_and_arithmetic():
    from services.ask_kernels import solve_math_text

    q = solve_math_text("解方程 x²-5x+6=0")
    assert q is not None and q.kernel == "algebra.quadratic_eq"
    assert "2" in q.answer and "3" in q.answer and any("因式分解" in s for s in q.steps)
    assert solve_math_text("x^2+2x+5=0").answer_value == "无实数根"
    ar = solve_math_text("计算：(-2)² + 4 × 3 = ?")
    assert ar is not None and ar.kernel.startswith("arith") and ar.answer == "16"
    assert solve_math_text("1/2 + 1/3 =").answer.startswith("5/6")
    assert solve_math_text("今天天气很好") is None
    assert solve_math_text("速度 v = 3 m/s，求路程") is None


def test_kernel_rejects_code_injection():
    from services.ask_kernels import solve_math_text

    assert solve_math_text("__import__('os').system('id') = 1") is None
    assert solve_math_text("x = (lambda: 1)()") is None


def test_chemistry_equation_detection():
    from services.ask_kernels import find_chemical_equation

    assert find_chemical_equation("配平：Fe + O₂ → Fe₃O₄") == "Fe + O2 = Fe3O4"
    assert find_chemical_equation("3x+5=20") is None


# ── 纯函数：判分 ────────────────────────────────────────────────────────────


def test_grade_deterministic_paths():
    from services.wrongbook_review_service import answer_type, grade_deterministic

    assert grade_deterministic("5", "x=5", "math") == (True, "kernel")
    assert grade_deterministic("x = 5", "5", "math")[0] is True
    assert grade_deterministic("0.5", "1/2", "math") == (True, "kernel")
    assert grade_deterministic("3.1416", "3.1416", "math")[0] is True
    assert grade_deterministic("4", "5", "math")[0] is False
    assert grade_deterministic("b", "B", "math") == (True, "rule")
    assert grade_deterministic("C", "B", "math") == (False, "rule")
    assert grade_deterministic("He's finished", "He has finished", "english")[0] is True
    assert grade_deterministic("", "5", "math") == (False, "rule")  # 空答 = 不会
    long_ans = "【解析】由题意得……(1) 略 (2) 略"
    assert answer_type(long_ans, "math") == "self"
    assert grade_deterministic("随便写", long_ans, "math") == (None, "none")
    assert answer_type("B", None) == "choice"
    assert answer_type("x=5", "math") == "numeric"


def test_schedule_and_graduation():
    from services.wrongbook_review_service import schedule_after_answer

    wq = WrongQuestion(id=uuid.uuid4(), question_text="q", review_count=0, review_correct_streak=0)
    t = datetime(2026, 10, 1, tzinfo=timezone.utc)
    r = schedule_after_answer(wq, is_correct=False, struggled=False, now=t)
    assert wq.review_correct_streak == 0 and wq.review_count == 1 and not r["graduated"]
    assert wq.fsrs_due is not None and wq.fsrs_card_json
    graduated = False
    for _ in range(6):
        t = wq.fsrs_due + timedelta(minutes=1)
        r = schedule_after_answer(wq, is_correct=True, struggled=False, now=t)
        if r["graduated"]:
            graduated = True
            break
    assert graduated and wq.graduated_at is not None and wq.review_correct_streak >= 3
    # 答错清零连对
    wq2 = WrongQuestion(id=uuid.uuid4(), question_text="q", review_count=3, review_correct_streak=2)
    schedule_after_answer(wq2, is_correct=False, struggled=False, now=t)
    assert wq2.review_correct_streak == 0


# ── API：拍照问题目 ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_photo_ask_typed_solve_feedback_wrongbook_history(students):
    a, b = students["a"], students["b"]
    async with _client() as c:
        r = await c.post("/v1/questions/ask", data={"text": "解方程：2x - 4 = 10"}, headers=_h(a))
        assert r.status_code == 200, r.text
        ask = r.json()
        assert ask["ocr"]["engine"] == "typed" and ask["subject"] == "math"
        ask_id = ask["ask_id"]

        s = await c.post(f"/v1/questions/ask/{ask_id}/solve", json={"text": "解方程：2x - 4 = 10"}, headers=_h(a))
        assert s.status_code == 200, s.text
        sol = s.json()
        assert sol["solver"] == "kernel" and sol["answer"] == "x = 7" and sol["hint"]
        assert sol["latency_ms"] < 3000

        # 别人碰不到
        assert (await c.post(f"/v1/questions/ask/{ask_id}/feedback", json={"understood": True}, headers=_h(b))).status_code == 404
        assert (await c.post(f"/v1/questions/ask/{ask_id}/feedback", json={"understood": True}, headers=_h(a))).status_code == 200

        w = await c.post("/v1/wrongbook/add", json={"record_id": ask_id}, headers=_h(a))
        assert w.status_code == 200 and w.json()["created"] is True
        w2 = await c.post("/v1/wrongbook/add", json={"record_id": ask_id}, headers=_h(a))
        assert w2.json() == {"wrong_question_id": w.json()["wrong_question_id"], "created": False}
        assert (await c.post("/v1/wrongbook/add", json={"record_id": ask_id}, headers=_h(b))).status_code == 404

        h = await c.get("/v1/questions/history", params={"source": "photo_ask"}, headers=_h(a))
        assert h.status_code == 200 and h.json()["total"] == 1
        item = h.json()["items"][0]
        assert item["source_label"] == "拍照提问" and item["wrong_question_id"]
        d = (await c.get(f"/v1/questions/history/{ask_id}", headers=_h(a))).json()
        assert d["correct_answer"] == "x = 7" and d["understood"] is True
        assert d["meta"]["solution"]["kernel"] == "algebra.linear"
        assert (await c.get(f"/v1/questions/history/{ask_id}", headers=_h(b))).status_code == 404
        assert (await c.get("/v1/questions/history", headers=_h(b))).json()["total"] == 0
        assert (await c.post("/v1/questions/ask", data={"text": "x"})).status_code == 401


@pytest.mark.asyncio
async def test_photo_ask_image_path_and_private_image(students, monkeypatch):
    a, b = students["a"], students["b"]
    stored: dict[str, bytes] = {}
    import services.photo_ask_service as pas
    import services.storage as storage

    monkeypatch.setattr(storage, "upload_question_image", lambda k, d, ct: stored.__setitem__(k, d))
    monkeypatch.setattr(storage, "download_question_image", lambda k: stored[k])

    async def fake_recognize(image: bytes) -> dict:
        assert image.startswith(b"\x89PNG")
        return {"text": "计算：(-2)² + 4 × 3 = ?", "subject": "math", "grade": None, "engine": "ocr", "ms": 42, "confidence": 0.94}

    monkeypatch.setattr(pas, "recognize_image", fake_recognize)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    async with _client() as c:
        r = await c.post("/v1/questions/ask", files={"image": ("q.png", io.BytesIO(png), "image/png")}, headers=_h(a))
        assert r.status_code == 200, r.text
        ask = r.json()
        assert ask["has_image"] and ask["ocr"]["engine"] == "ocr" and "(-2)" in ask["text"]
        key = next(iter(stored))
        assert key.startswith(f"ask/{a}/")
        img = await c.get(f"/v1/questions/records/{ask['record_id']}/image", headers=_h(a))
        assert img.status_code == 200 and img.headers["content-type"] == "image/png"
        assert (await c.get(f"/v1/questions/records/{ask['record_id']}/image", headers=_h(b))).status_code == 404
        bad = await c.post("/v1/questions/ask", files={"image": ("x.gif", io.BytesIO(b"GIF89a...."), "image/gif")}, headers=_h(a))
        assert bad.status_code == 415
        s = (await c.post(f"/v1/questions/ask/{ask['ask_id']}/solve", json={"text": ask["text"]}, headers=_h(a))).json()
        assert s["answer"] == "16"


@pytest.mark.asyncio
async def test_photo_ask_llm_unavailable_is_graceful(students, monkeypatch):
    a = students["a"]
    import services.photo_ask_service as pas

    async def no_llm(**_kw):
        return None

    monkeypatch.setattr(pas, "_llm_call", no_llm)
    async with _client() as c:
        ask = (await c.post("/v1/questions/ask", data={"text": "《背影》表达了作者怎样的情感？", "subject": "chinese"}, headers=_h(a))).json()
        s = await c.post(f"/v1/questions/ask/{ask['ask_id']}/solve", json={"text": ask["text"]}, headers=_h(a))
        assert s.status_code == 200 and s.json()["status"] == "llm_unavailable" and s.json()["solver"] == "none"
        f = await c.post(f"/v1/questions/ask/{ask['ask_id']}/followup", json={"message": "没懂"}, headers=_h(a))
        assert f.status_code == 200 and f.json()["status"] == "llm_unavailable"


@pytest.mark.asyncio
async def test_photo_ask_llm_solution_and_followup(students, monkeypatch):
    a = students["a"]
    import services.photo_ask_service as pas

    calls: list[dict] = []

    async def fake_llm(**kw):
        calls.append(kw)
        if kw.get("json_mode"):
            return '{"hint": "想想光合作用需要什么", "steps": ["第一步", "第二步"], "answer": "光、水、二氧化碳", "explanation": "光合作用条件"}'
        return "我们换个例子来说……你明白了吗？"

    monkeypatch.setattr(pas, "_llm_call", fake_llm)
    async with _client() as c:
        ask = (await c.post("/v1/questions/ask", data={"text": "光合作用需要哪些条件？", "subject": "生物"}, headers=_h(a))).json()
        s = (await c.post(f"/v1/questions/ask/{ask['ask_id']}/solve", json={"text": ask["text"], "grade": "初一"}, headers=_h(a))).json()
        assert s["solver"] == "llm" and s["steps"] == ["第一步", "第二步"] and s["hint"]
        assert "初一" in calls[0]["system"]
        f = (await c.post(f"/v1/questions/ask/{ask['ask_id']}/followup", json={"message": "为什么要光？"}, headers=_h(a))).json()
        assert f["status"] == "ok"
        d = (await c.get(f"/v1/questions/history/{ask['ask_id']}", headers=_h(a))).json()
        assert d["understood"] is False and len(d["meta"]["followups"]) == 2


# ── API：10 分钟错题复习 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_review_today_session_answer_finish(students):
    a, b = students["a"], students["b"]
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        due_id = uuid.uuid4()
        db.add(WrongQuestion(id=due_id, student_id=a, subject="math", question_text="3+4=?", correct_answer="7",
                             fsrs_due=now - timedelta(days=2), source="practice"))
        for i in range(14):
            db.add(WrongQuestion(student_id=a, subject="math", question_text=f"第{i}题：{i}+1=?", correct_answer=str(i + 1),
                                 source="quiz"))
        db.add(WrongQuestion(student_id=a, subject="math", question_text="未来的题 1+1=?", correct_answer="2",
                             fsrs_due=now + timedelta(days=20)))
        db.add(WrongQuestion(student_id=a, subject="math", question_text="毕业的题", correct_answer="1",
                             graduated_at=now))
        db.add(WrongQuestion(student_id=a, subject="math", question_text="证明题", correct_answer="【解析】略（1）…",
                             fsrs_due=now - timedelta(days=1)))
        db.add(WrongQuestion(student_id=b, subject="math", question_text="别人的", correct_answer="1"))
        await db.commit()

    async with _client() as c:
        t = await c.get("/v1/review/today", headers=_h(a))
        assert t.status_code == 200, t.text
        sess = t.json()
        items = sess["items"]
        assert 1 <= len(items) <= 10
        assert sess["est_total_seconds"] <= 630 and sess["budget_seconds"] == 600
        assert items[0]["question_text"] in ("3+4=?", "证明题")  # 已到期的先出
        texts = {i["question_text"] for i in items}
        assert "未来的题 1+1=?" not in texts and "毕业的题" not in texts and "别人的" not in texts
        proof = next((i for i in items if i["question_text"] == "证明题"), None)
        if proof:
            assert proof["answer_type"] == "self"

        r1 = await c.post("/v1/review/today/answer", json={"session_id": sess["session_id"], "item_id": str(due_id), "answer": "7", "duration_ms": 8000}, headers=_h(a))
        assert r1.status_code == 200, r1.text
        assert r1.json()["is_correct"] is True and r1.json()["grader"] == "kernel" and r1.json()["next_due"]
        # 别人的题 → 404
        assert (await c.post("/v1/review/today/answer", json={"item_id": str(due_id), "answer": "7"}, headers=_h(b))).status_code == 404
        if proof:
            r2 = await c.post("/v1/review/today/answer", json={"item_id": proof["item_id"], "answer": "我写了一段证明"}, headers=_h(a))
            body = r2.json()
            if body["needs_self_grade"]:
                assert body["is_correct"] is None and body["correct_answer"]
                r3 = await c.post("/v1/review/today/answer", json={"item_id": proof["item_id"], "answer": "我写了一段证明", "self_grade": False}, headers=_h(a))
                assert r3.json()["is_correct"] is False and r3.json()["grader"] == "self"

        fin = await c.post("/v1/review/today/finish", json={"session_id": sess["session_id"], "answered": 2, "correct": 1, "duration_seconds": 300}, headers=_h(a))
        assert fin.status_code == 200 and fin.json()["streak"] == 1 and fin.json()["message"]

    recs = await _records(a, "review")
    assert recs and recs[0].wrong_question_id == due_id and recs[0].is_correct is True and recs[0].grader == "kernel"
    async with SessionLocal() as db:
        wq = await db.get(WrongQuestion, due_id)
        assert wq.review_count == 1 and wq.review_correct_streak == 1 and wq.fsrs_due > now


@pytest.mark.asyncio
async def test_review_today_empty(students):
    async with _client() as c:
        t = (await c.get("/v1/review/today", headers=_h(students["b"]))).json()
        assert t["items"] == [] and t["total_due"] == 0 and t["streak"] == 0


@pytest.mark.asyncio
async def test_history_filters(students):
    from services.question_record_service import record_question

    a = students["a"]
    await record_question(student_id=a, source="quiz", question_text="1+1", subject="math", is_correct=True, grader="rule")
    await record_question(student_id=a, source="practice", question_text="2+2", subject="math", is_correct=False, grader="rule")
    await record_question(student_id=a, source="chat", question_text="what", subject="english")
    async with _client() as c:
        g = lambda **p: c.get("/v1/questions/history", params=p, headers=_h(a))  # noqa: E731
        assert (await g()).json()["total"] == 3
        assert (await g(result="wrong")).json()["items"][0]["question_text"] == "2+2"
        assert (await g(result="unknown")).json()["total"] == 1
        assert (await g(subject="english")).json()["total"] == 1
        assert (await g(source="quiz")).json()["total"] == 1
        today = datetime.now(timezone.utc).date()
        assert (await g(since=str(today - timedelta(days=1)), until=str(today + timedelta(days=1)))).json()["total"] == 3
        assert (await g(since=str(today + timedelta(days=3)))).json()["total"] == 0
        assert (await g(limit=2)).json()["total"] == 3 and len((await g(limit=2)).json()["items"]) == 2


# ── 每个接线来源都落记录 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_practice_submit_writes_record_and_wrongbook(students):
    a = students["a"]
    bank_id = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(WrongQuestion(id=bank_id, student_id=None, subject="math", question_text="QR-BANK 选 B",
                             correct_answer="B", knowledge_points={"qr-kc": "qr-kc"}))
        await db.commit()
    try:
        async with _client() as c:
            r = await c.post("/v1/practice/submit", json={"student_id": str(a), "question_id": str(bank_id), "ku_id": "qr-kc", "student_answer": "C"}, headers=_h(a))
            assert r.status_code == 200, r.text
            assert r.json()["is_correct"] is False
        recs = await _records(a, "practice")
        assert len(recs) == 1 and recs[0].is_correct is False and recs[0].question_text == "QR-BANK 选 B"
        assert recs[0].wrong_question_id is not None and recs[0].kc_ids == ["qr-kc"]
    finally:
        async with SessionLocal() as db:
            await db.execute(text("DELETE FROM wrong_questions WHERE id = :i"), {"i": bank_id})
            await db.commit()


@pytest.mark.asyncio
async def test_record_failure_never_breaks_main_flow(students, monkeypatch):
    a = students["a"]
    import services.question_record_service as qrs

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(qrs, "_session_factory", boom)
    assert await qrs.record_question(student_id=a, source="practice", question_text="x") is None
    bank_id = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(WrongQuestion(id=bank_id, student_id=None, subject="math", question_text="QR-BANK2 1+1=?",
                             correct_answer="2", knowledge_points={"qr-kc": "qr-kc"}))
        await db.commit()
    try:
        async with _client() as c:
            r = await c.post("/v1/practice/submit", json={"student_id": str(a), "question_id": str(bank_id), "ku_id": "qr-kc", "student_answer": "2"}, headers=_h(a))
            assert r.status_code == 200 and r.json()["is_correct"] is True
    finally:
        async with SessionLocal() as db:
            await db.execute(text("DELETE FROM wrong_questions WHERE id = :i"), {"i": bank_id})
            await db.commit()


@pytest.mark.asyncio
async def test_mcp_submit_answer_writes_record_and_wrongbook(students):
    a = students["a"]
    qid = f"q-qr-{a.hex[:12]}"
    async with SessionLocal() as db:
        await db.execute(
            text("INSERT INTO gate.pending_question (question_id, student_id, kc_id, prompt, expected, qtype) "
                 "VALUES (:q, CAST(:s AS uuid), 'qr-kc2', 'QR 3+4=?', '7', 'solve')"),
            {"q": qid, "s": str(a)},
        )
        await db.commit()
    try:
        async with _client() as c:
            r = await c.post("/mcp/SubmitAnswer", json={"student_id": str(a), "question_id": qid, "answer": "8", "time_spent_seconds": 12}, headers=_h(a))
            assert r.status_code == 200, r.text
            assert r.json()["is_correct"] is False
            assert "7" not in str(r.json().get("expected", ""))  # 返回体红线不变
        recs = await _records(a, "mcp")
        assert len(recs) == 1 and recs[0].question_text == "QR 3+4=?" and recs[0].is_correct is False
        assert recs[0].duration_ms == 12000 and recs[0].grader == "kernel"
        assert recs[0].wrong_question_id is not None
        async with SessionLocal() as db:
            wq = await db.get(WrongQuestion, recs[0].wrong_question_id)
            assert wq.student_id == a and wq.source == "mcp" and wq.correct_answer == "7"
    finally:
        async with SessionLocal() as db:
            await db.execute(text("DELETE FROM gate.pending_question WHERE student_id = CAST(:s AS uuid)"), {"s": str(a)})
            await db.commit()


@pytest.mark.asyncio
async def test_quiz_submit_writes_records(students):
    a = students["a"]
    bank = [uuid.uuid4(), uuid.uuid4()]
    quiz_id = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(WrongQuestion(id=bank[0], student_id=None, subject="math", question_text="QRQ 2+2=?", correct_answer="4",
                             knowledge_points={"qr-kc": "qr-kc"}))
        db.add(WrongQuestion(id=bank[1], student_id=None, subject="math", question_text="QRQ 选 B", correct_answer="B",
                             knowledge_points={"qr-kc": "qr-kc"}))
        await db.flush()
        db.add(TimedQuiz(id=quiz_id, student_id=a, items=[
            {"question_id": str(bank[0]), "ku_id": "qr-kc", "question_text": "QRQ 2+2=?"},
            {"question_id": str(bank[1]), "ku_id": "qr-kc", "question_text": "QRQ 选 B"},
        ]))
        await db.commit()
    try:
        async with _client() as c:
            r = await c.post(f"/v1/quiz/{quiz_id}/submit", params={"student_id": str(a)},
                             json={"answers": [{"question_id": str(bank[0]), "student_answer": "4"},
                                               {"question_id": str(bank[1]), "student_answer": "C"}],
                                   "time_spent_seconds": 60}, headers=_h(a))
            assert r.status_code == 200, r.text
        recs = await _records(a, "quiz")
        assert len(recs) == 2
        by_text = {r.question_text: r for r in recs}
        assert by_text["QRQ 2+2=?"].is_correct is True
        assert by_text["QRQ 选 B"].is_correct is False and by_text["QRQ 选 B"].wrong_question_id is not None
    finally:
        async with SessionLocal() as db:
            await db.execute(text("DELETE FROM timed_quizzes WHERE id = :i"), {"i": quiz_id})
            await db.execute(text("DELETE FROM wrong_questions WHERE id = ANY(:ids)"), {"ids": bank})
            await db.commit()


@pytest.mark.asyncio
async def test_solver_endpoints_write_records(students):
    a = students["a"]
    async with _client() as c:
        r = await c.post("/v1/chemistry/equation/balance", json={"reactants": ["H2", "O2"], "products": ["H2O"]}, headers=_h(a))
        assert r.status_code == 200, r.text
        e = await c.post("/v1/english/check", json={"text": "He's finished", "accepted": ["He has finished"], "type": "fill"}, headers=_h(a))
        assert e.status_code == 200, e.text
    recs = await _records(a, "solver")
    tools = {r.meta["tool"]: r for r in recs}
    assert "chemistry.balance" in tools and tools["chemistry.balance"].question_text.startswith("配平：")
    assert "english.check" in tools and tools["english.check"].is_correct is True


@pytest.mark.asyncio
async def test_kc_review_submit_writes_record(students, monkeypatch):
    a = students["a"]
    import services.review_service as rs

    async def fake_answer(db, student_id, kc_id):
        return "12"

    async def fake_probe(db, student_id, kc_id, now=None):
        return "review", None

    async def fake_pi(*args, **kwargs):
        return {}

    monkeypatch.setattr(rs, "_answer_for_review", fake_answer)
    monkeypatch.setattr(rs, "_probe_context", fake_probe)
    import services.cognitive_service as cs

    monkeypatch.setattr(cs, "process_interaction", fake_pi)
    async with _client() as c:
        r = await c.post(f"/v1/review/submit/{a}", json={"ku_id": "qr-kc", "answer": "12"}, headers=_h(a))
        assert r.status_code == 200, r.text
    recs = await _records(a, "kc_review")
    assert len(recs) == 1 and recs[0].is_correct is True and recs[0].question_text.startswith("知识点复习")


def test_purge_lists_question_records():
    from services.purge_service import _STUDENT_TABLES

    assert ("question_records", "student_id") in _STUDENT_TABLES


@pytest.mark.asyncio
async def test_recognize_prefers_vision_falls_back_to_ocr(monkeypatch):
    import services.photo_ask_service as pas

    async def ocr_ok(image):
        return {"text": "1. 解方程：3x+5=20，求× 的值。", "confidence": 0.94}

    async def vision_ok(b64):
        return {"text": "解方程：3x+5=20", "subject": "math", "grade": "初一"}

    async def vision_down(b64):
        raise RuntimeError("gateway reset")

    monkeypatch.setenv("MNEME_ASK_VISION", "1")  # 视觉默认关闭，这里显式打开测竞速
    monkeypatch.setattr(pas, "_ocr_sidecar", ocr_ok)
    monkeypatch.setattr(pas, "_vision_cooldown_until", 0.0)
    monkeypatch.setattr(pas, "_vision", vision_ok)
    r = await pas.recognize_image(b"img")
    assert r["engine"] == "vision" and r["grade"] == "初一"

    monkeypatch.setattr(pas, "_vision", vision_down)
    r = await pas.recognize_image(b"img")
    assert r["engine"] == "ocr" and r["subject"] == "math"
    assert "求 x 的" in r["text"]  # OCR 把变量 x 认成乘号的修正
    assert pas._vision_cooldown_until > 0  # 熔断：之后直接走 OCR

    async def ocr_down(image):
        raise RuntimeError("no ocr")

    monkeypatch.setattr(pas, "_ocr_sidecar", ocr_down)
    r = await pas.recognize_image(b"img")
    assert r["engine"] == "none" and r["text"] == ""


@pytest.mark.asyncio
async def test_wrongbook_add_without_kc_stores_sql_null_and_getpath_ok(students):
    """回归：无知识点的记录加入错题本，knowledge_points / kc_ids / meta 必须是 SQL NULL，
    不能是 JSON 'null' 标量（否则 _CONTENT_KC_SQL 的 jsonb_object_keys 报错 → GetPath 500）。"""
    a = students["a"]
    async with _client() as c:
        r = await c.post("/v1/questions/ask", data={"text": "这句话怎么理解？"}, headers=_h(a))
        assert r.status_code == 200, r.text
        ask_id = r.json()["ask_id"]
        w = await c.post("/v1/wrongbook/add", json={"record_id": ask_id}, headers=_h(a))
        assert w.status_code == 200, w.text
        wq_id = w.json()["wrong_question_id"]
        async with SessionLocal() as db:
            kp_null = (
                await db.execute(
                    text("SELECT knowledge_points IS NULL, jsonb_typeof(knowledge_points) FROM wrong_questions WHERE id = :i"),
                    {"i": wq_id},
                )
            ).one()
            assert kp_null[1] != "null"
            rows = (
                await db.execute(
                    text("SELECT jsonb_typeof(kc_ids), jsonb_typeof(meta) FROM question_records WHERE student_id = :s"),
                    {"s": str(a)},
                )
            ).all()
            assert rows and all(k != "null" and m != "null" for k, m in rows)
        g = await c.post("/mcp/GetPath", json={"student_id": str(a)}, headers=_h(a))
        assert g.status_code == 200, g.text


@pytest.mark.asyncio
async def test_question_record_none_json_fields_are_sql_null(students):
    a = students["a"]
    rid = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(QuestionRecord(id=rid, student_id=a, source="photo_ask", kc_ids=None, meta=None))
        await db.commit()
        row = (
            await db.execute(
                text("SELECT kc_ids IS NULL, meta IS NULL FROM question_records WHERE id = :i"), {"i": str(rid)}
            )
        ).one()
        assert row == (True, True)
