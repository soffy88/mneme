"""S3-A RequestQuestion（人在环 poser）—— 出题但只出不答；expected 只进 gate.pending_question。

题库优先；返回体/prompt 绝无 expected；幂等（已有 pending 直接返回）。单 session 回滚。
"""

from __future__ import annotations

import json
import uuid

import pytest

pytest.importorskip("mneme_core")

from sqlalchemy import text  # noqa: E402

from obase.db import SessionLocal  # noqa: E402
from services.mcp_router import tool_request_question  # noqa: E402
from services.models import User, UserRole, WrongQuestion  # noqa: E402

QUANT_KC = "renjiao-math-g10-a-ku-二次函数的零点"  # 题库有 57 题
KU004 = "renjiao-math-g10-a-ku004"  # 定性 → open 自我解释


@pytest.fixture
async def quant_bank_question():
    """自包含题库夹具：tool_request_question 的量化路径优先从 wrong_questions 出题，
    无清洁题库题才回落 LLM（需真实 provider）。这里种一道能过全部题库过滤的
    选择题（needs_image=False、无 <ImageHere>、profiler_analysis.grade=高一、
    correct_answer 单字母），让测试走确定性 bank 路径、不碰 LLM。测完即清。"""
    qid = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(
            WrongQuestion(
                id=qid,
                student_id=None,  # 系统种子题
                subject="math",
                question_text="函数 y=x²-2x-3 的零点是？",
                correct_answer="A",
                knowledge_points={QUANT_KC: "零点"},
                needs_image=False,
                profiler_analysis={
                    "grade": "高一",
                    "options": "A. -1 和 3\nB. 1 和 -3\nC. 1 和 3\nD. -1 和 -3",
                },
            )
        )
        await db.commit()

    yield qid

    async with SessionLocal() as db:
        await db.execute(
            text("DELETE FROM wrong_questions WHERE id=:id"), {"id": str(qid)}
        )
        await db.commit()


@pytest.mark.asyncio
async def test_request_question_bank_no_expected_leak(quant_bank_question):
    sid = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
        await db.flush()

        r = await tool_request_question(db, sid, QUANT_KC)
        # 出到题（题库或生成），有 question_id/prompt/qtype
        assert r.get("question_id") and r.get("prompt"), r
        assert r.get("qtype") in ("solve", "choice", "fill", "short"), r
        # 返回体绝无 expected
        assert "expected" not in json.dumps(r, ensure_ascii=False)

        # expected 只存服务端 gate.pending_question
        row = (
            await db.execute(
                text(
                    "SELECT expected FROM gate.pending_question "
                    "WHERE student_id=:s AND question_id=:q"
                ),
                {"s": str(sid), "q": r["question_id"]},
            )
        ).first()
        assert row is not None and row[0] is not None  # expected 在服务端


@pytest.mark.asyncio
async def test_request_question_idempotent(quant_bank_question):
    sid = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
        await db.flush()

        r1 = await tool_request_question(db, sid, QUANT_KC)
        r2 = await tool_request_question(db, sid, QUANT_KC)  # 已有 pending
        assert r2.get("source") == "pending"
        assert r2["question_id"] == r1["question_id"]  # 不重复出题


@pytest.mark.asyncio
async def test_request_question_qualitative_open():
    sid = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
        await db.flush()

        r = await tool_request_question(db, sid, KU004)
        assert r.get("qtype") == "open"  # 定性 → 开放自我解释
        assert "expected" not in json.dumps(r, ensure_ascii=False)
        # open 题服务端 expected 为 NULL（无标准答案）
        row = (
            await db.execute(
                text(
                    "SELECT expected FROM gate.pending_question "
                    "WHERE student_id=:s AND question_id=:q"
                ),
                {"s": str(sid), "q": r["question_id"]},
            )
        ).first()
        assert row is not None and row[0] is None
