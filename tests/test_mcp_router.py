"""②-3a MCP 读工具 — NextObjective / GetKCInfo / CheckMastery。

重点红线测试：期望答案（expected）绝不出现在任何工具响应里。
单 session 不 commit，退出自动回滚。需 mneme_core（②-0）。
"""

from __future__ import annotations

import json
import uuid

import pytest

pytest.importorskip("mneme_core")

from obase.db import SessionLocal  # noqa: E402
from services import gate_store  # noqa: E402
from services.mcp_router import (  # noqa: E402
    tool_check_mastery,
    tool_get_kc_info,
    tool_next_objective,
)
from services.models import (  # noqa: E402
    InteractionEvent,
    InteractionSource,
    KCMastery,
    User,
    UserRole,
)

KU004 = "renjiao-math-g10-a-ku004"  # 有 rubric（定性）
QUANT_KC = "renjiao-math-g10-a-ku-二次函数的零点"  # 无 rubric（量化）
SECRET = "TOP_SECRET_ANSWER_42"


async def _mk_student(db, sid):
    db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
    await db.flush()


@pytest.mark.asyncio
async def test_next_objective_never_leaks_expected():
    """红线：pose 一道带 expected 的题后，NextObjective 响应绝不含 expected。"""
    sid = uuid.uuid4()
    qid = f"q-{uuid.uuid4().hex}"
    async with SessionLocal() as db:
        await _mk_student(db, sid)
        await gate_store.pose_question(
            db,
            question_id=qid,
            student_id=sid,
            kc_id=QUANT_KC,
            prompt="求二次函数零点：x^2-5x+6=0",
            expected=SECRET,
            qtype="fill",
        )
        resp = await tool_next_objective(db, sid, [QUANT_KC, KU004])

        assert resp["action"] == "answer_pending"
        assert resp["has_pending"] is True
        assert resp["pending_question"]["question_id"] == qid
        assert resp["pending_question"]["prompt"].startswith("求二次函数零点")
        # expected 不得以任何形式出现在整个响应里
        assert SECRET not in json.dumps(resp, ensure_ascii=False)
        assert "expected" not in resp["pending_question"]


@pytest.mark.asyncio
async def test_get_kc_info_returns_rubric_for_qualitative():
    """GetKCInfo：ku004 有 rubric → gate_type=qualitative + rubric 4 维。"""
    async with SessionLocal() as db:
        info = await tool_get_kc_info(db, KU004)
        assert info["gate_type"] == "qualitative"
        assert info["rubric"] is not None
        assert len(info["rubric"]["dimensions"]) == 4
        assert info["name"]  # 有名字


@pytest.mark.asyncio
async def test_get_kc_info_no_rubric_for_quantitative():
    """量化 KC 无 rubric → rubric=None（fail-safe：不可 assess）。"""
    async with SessionLocal() as db:
        info = await tool_get_kc_info(db, QUANT_KC)
        assert info["gate_type"] == "quantitative"
        assert info["rubric"] is None


@pytest.mark.asyncio
async def test_rubric_left_join():
    """A7 具名：GetKCInfo 对 gate.rubric 做 LEFT JOIN，两态都正确。

    命中 → rubric 非空 + gate_type=qualitative；未命中 → rubric=None + gate_type=quantitative。
    """
    async with SessionLocal() as db:
        hit = await tool_get_kc_info(db, KU004)  # 有 rubric
        assert hit["rubric"] is not None
        assert len(hit["rubric"]["dimensions"]) == 4
        assert hit["gate_type"] == "qualitative"

        miss = await tool_get_kc_info(db, QUANT_KC)  # 无 rubric
        assert miss["rubric"] is None
        assert miss["gate_type"] == "quantitative"


@pytest.mark.asyncio
async def test_check_mastery_reports_mastered_quant():
    """CheckMastery：p=0.98 n_obs=3 → 下界过门 → is_mastered True。"""
    sid = uuid.uuid4()
    async with SessionLocal() as db:
        await _mk_student(db, sid)
        db.add(
            KCMastery(
                student_id=sid,
                knowledge_point=QUANT_KC,
                p_mastery=0.98,
                p_init=0.3,
                p_transit=0.3,
                p_guess=0.2,
                p_slip=0.1,
            )
        )
        for _ in range(3):
            db.add(
                InteractionEvent(
                    student_id=sid,
                    knowledge_point=QUANT_KC,
                    source=InteractionSource.paper,
                    is_correct=True,
                )
            )
        await db.flush()

        m = await tool_check_mastery(db, sid, QUANT_KC)
        assert m["n_obs"] == 3
        assert m["is_mastered"] is True
        assert m["gate_type"] == "quantitative"
