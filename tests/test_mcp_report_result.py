"""②-3c 定性写路径 — ReportResult → guard → gate.evidence + gate.qualitative_mastery。

需 mneme_core（②-0）。单 session 不 commit，退出回滚。
"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("mneme_core")

from mneme_core.service.verdict_guard import GuardRejection  # noqa: E402

from obase.db import SessionLocal  # noqa: E402
from services import gate_store  # noqa: E402
from services.mcp_router import tool_report_result  # noqa: E402
from services.models import User, UserRole  # noqa: E402

KU004 = "renjiao-math-g10-a-ku004"  # 有 rubric → qualitative
EVIDENCE = {"passed": True, "spans": [[0, 5, "对应关系本质"]]}


async def _mk_student(db):
    sid = uuid.uuid4()
    db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
    await db.flush()
    return sid


@pytest.mark.asyncio
async def test_llm_verified_passes_writes_qualitative_mastery():
    async with SessionLocal() as db:
        sid = await _mk_student(db)
        res = await tool_report_result(
            db,
            student_id=sid,
            kc_id=KU004,
            question_id=None,
            is_correct=True,
            verdict_source="llm_verified",
            evidence=EVIDENCE,
            model_id="qwen-max",
        )
        assert res["recorded"] is True
        assert res["gate_type"] == "qualitative"
        assert res["evidence_ref"]  # 有 ref
        # 定性过门落库
        got = await gate_store.get_qualitative_mastery_map(db, sid)
        assert got.get(KU004) is True


@pytest.mark.asyncio
async def test_llm_verified_fail_records_not_passed():
    async with SessionLocal() as db:
        sid = await _mk_student(db)
        await tool_report_result(
            db,
            student_id=sid,
            kc_id=KU004,
            question_id=None,
            is_correct=False,
            verdict_source="llm_verified",
            evidence={"passed": False, "spans": []},
            model_id="qwen-max",
        )
        got = await gate_store.get_qualitative_mastery_map(db, sid)
        assert got.get(KU004) is False


@pytest.mark.asyncio
async def test_llm_verified_without_evidence_rejected():
    """DoD：无 evidence 的 llm_verified 被拒（零写入）。"""
    async with SessionLocal() as db:
        sid = await _mk_student(db)
        with pytest.raises(GuardRejection):
            await tool_report_result(
                db,
                student_id=sid,
                kc_id=KU004,
                question_id=None,
                is_correct=True,
                verdict_source="llm_verified",
                evidence=None,
            )
        # 零写入
        assert await gate_store.get_qualitative_mastery_map(db, sid) == {}


@pytest.mark.asyncio
async def test_agent_cannot_claim_deterministic():
    """红线：origin=agent + deterministic → guard 拒绝。"""
    async with SessionLocal() as db:
        sid = await _mk_student(db)
        with pytest.raises(GuardRejection):
            await tool_report_result(
                db,
                student_id=sid,
                kc_id=KU004,
                question_id=None,
                is_correct=True,
                verdict_source="deterministic",
            )
