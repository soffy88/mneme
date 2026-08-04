"""②-3b-ii 确定性写路径 e2e — PoseQuestion→SubmitAnswer→既有 process_interaction。

验证 DoD 铁律：掌握度经既有 process_interaction 写进 kc_mastery。
单 session 不 commit，退出回滚。需 mneme_core（②-0）。
"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("mneme_core")

from sqlalchemy import select  # noqa: E402

from obase.db import SessionLocal  # noqa: E402
from services import gate_store  # noqa: E402
from services.mcp_router import tool_pose_question, tool_submit_answer  # noqa: E402
from services.models import KCMastery, User, UserRole  # noqa: E402

QUANT_KC = "renjiao-math-g10-a-ku-二次函数的零点"


async def _mk_student(db):
    sid = uuid.uuid4()
    db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
    await db.flush()
    return sid


async def _mastery_row(db, sid, kc):
    return (
        await db.execute(
            select(KCMastery).where(
                KCMastery.student_id == sid, KCMastery.knowledge_point == kc
            )
        )
    ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_correct_solve_writes_kc_mastery_via_process_interaction():
    """答对 solve 题 → grade_math True → 既有 process_interaction 建/更新 kc_mastery。"""
    async with SessionLocal() as db:
        sid = await _mk_student(db)
        qid = f"q-{uuid.uuid4().hex}"
        await tool_pose_question(
            db,
            student_id=sid,
            kc_id=QUANT_KC,
            question_id=qid,
            prompt="解 x^2-5x+6=0",
            expected="x=2 或 x=3",
            qtype="solve",
        )
        # 冷启动：作答前无 kc_mastery
        assert await _mastery_row(db, sid, QUANT_KC) is None

        res = await tool_submit_answer(
            db, student_id=sid, question_id=qid, answer="x=3, x=2"
        )
        assert res["graded"] is True
        assert res["is_correct"] is True
        assert res["verdict_source"] == "deterministic"

        # DoD 铁律：掌握度经 process_interaction 写进 kc_mastery
        row = await _mastery_row(db, sid, QUANT_KC)
        assert row is not None and row.p_mastery is not None

        # pending 已清
        assert (
            await gate_store.get_pending(db, student_id=sid, question_id=qid)
        ) is None


@pytest.mark.asyncio
async def test_wrong_solve_graded_incorrect():
    async with SessionLocal() as db:
        sid = await _mk_student(db)
        qid = f"q-{uuid.uuid4().hex}"
        await tool_pose_question(
            db,
            student_id=sid,
            kc_id=QUANT_KC,
            question_id=qid,
            prompt="解 x^2-5x+6=0",
            expected="x=2 或 x=3",
            qtype="solve",
        )
        res = await tool_submit_answer(
            db, student_id=sid, question_id=qid, answer="x=1"
        )
        assert res["graded"] is True and res["is_correct"] is False


@pytest.mark.asyncio
async def test_choice_via_answer_match():
    async with SessionLocal() as db:
        sid = await _mk_student(db)
        qid = f"q-{uuid.uuid4().hex}"
        await tool_pose_question(
            db,
            student_id=sid,
            kc_id=QUANT_KC,
            question_id=qid,
            prompt="选正确项",
            expected="A",
            qtype="choice",
        )
        res = await tool_submit_answer(db, student_id=sid, question_id=qid, answer="a")
        assert res["is_correct"] is True


@pytest.mark.asyncio
async def test_open_needs_qualitative_zero_write():
    """open 题 → needs_qualitative，零写入，pending 保留（交 assess→ReportResult）。"""
    async with SessionLocal() as db:
        sid = await _mk_student(db)
        qid = f"q-{uuid.uuid4().hex}"
        await tool_pose_question(
            db,
            student_id=sid,
            kc_id=QUANT_KC,
            question_id=qid,
            prompt="解释什么是函数",
            expected=None,
            qtype="open",
        )
        res = await tool_submit_answer(
            db, student_id=sid, question_id=qid, answer="函数是一种对应关系"
        )
        assert res.get("needs_qualitative") is True
        # 零写入：无 kc_mastery、pending 仍在
        assert await _mastery_row(db, sid, QUANT_KC) is None
        assert (
            await gate_store.get_pending(db, student_id=sid, question_id=qid)
        ) is not None
