"""缺口单点练闭环服务层测试（纯逻辑 + evaluate_return 桩 DB）。

链路：weak_roots → 5–10 道单点微题 → 确定性判分推进 → 练完只读核对门禁。
掌握度回写走 mcp_router 的 SubmitAnswer 唯一写路径，不在本服务内发生。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services import gap_drill_service as gds
from services import prereq_diagnosis_service as pds


def _topic_with_bank(min_q: int = 1) -> str:
    g = pds.graph()
    for t in g.topics:
        if len(g.bank.get(t["id"], [])) >= min_q:
            return t["id"]
    raise AssertionError("题库为空，无法测试")


def _roots_for(topic_id: str) -> list[dict]:
    return [{"ku_id": pds.to_ku_id(topic_id), "pending_prereqs": [pds.to_ku_id(topic_id)]}]


def test_build_drill_clamps_count_and_hides_answers():
    tid = _topic_with_bank()
    out = gds.build_drill(_roots_for(tid), count=3, seed="testseed1")
    assert out["requested"] == 5  # 下限 5
    assert out["available"] >= 1
    q = out["next"]["question"]
    assert "answer" not in q and "accept" not in q  # 答案不外发
    assert out["targets"][0]["ku_id"] == pds.to_ku_id(tid)
    # 会话不含 student_id（PII 不进客户端存档）
    assert "student" not in json.dumps(out["session"])


def test_build_drill_unknown_root_rejected():
    with pytest.raises(gds.GapDrillError):
        gds.build_drill([{"ku_id": "cnmath:cnm_nope"}], seed="s")


def test_answer_flow_advances_and_finishes():
    tid = _topic_with_bank()
    out = gds.build_drill(_roots_for(tid), count=5, seed="testseed2")
    session = out["session"]
    total = len(session["items"])
    seen_correct = 0
    for _ in range(total):
        ref = session["items"][session["index"]]
        if ref["kind"] == "bank":
            ans = pds.question_by_id(ref["question_id"])["answer"]
            res = gds.answer_drill(session, user_answer=str(ans))
            if res["needs_self_assessment"]:
                res = gds.answer_drill(session, result="correct")
                assert res["answered"]["self_assessed"] is True
            else:
                assert res["answered"]["self_assessed"] is False
                assert res["answered"]["ku_id"] == pds.to_ku_id(tid)
        else:
            res = gds.answer_drill(session, result="skip")
            assert res["answered"]["self_assessed"] is True
        assert res["applied"] is True
        session = res["session"]
        seen_correct += 1
    assert session["finished"] is True
    assert res["progress"]["done"] == total
    assert seen_correct == total


def test_answer_after_finish_rejected():
    tid = _topic_with_bank()
    out = gds.build_drill(_roots_for(tid), count=5, seed="testseed3")
    session = out["session"]
    for _ in range(len(session["items"])):
        session = gds.answer_drill(session, result="skip")["session"]
    with pytest.raises(gds.GapDrillError):
        gds.answer_drill(session, result="skip")


def test_session_tampering_rejected():
    with pytest.raises(gds.GapDrillError):
        gds.answer_drill({"bogus": True}, result="skip")


def test_variant_expected_answer_deterministic():
    """有变式被生成时：服务端两次重算的期望答案必须一致（回写靠它）。"""
    g = pds.graph()
    found = None
    for t in g.topics[:80]:
        if not g.bank.get(t["id"]):
            continue
        out = gds.build_drill(_roots_for(t["id"]), count=10, seed="vartest")
        for ref in out["session"]["items"]:
            if ref["kind"] == "variant":
                found = ref
                break
        if found:
            break
    if found is None:
        pytest.skip("样本 topic 均未生成变式（内核覆盖不足），跳过")
    a = gds.expected_answer(found)
    b = gds.expected_answer(found)
    assert a is not None and a == b and a["submit_qtype"] == "fill"


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


@pytest.mark.asyncio
async def test_evaluate_return_reads_gate():
    tid = _topic_with_bank()
    out = gds.build_drill(_roots_for(tid), count=5, seed="evalseed")
    session = out["session"]
    session["finished"] = True
    ku_id = session["targets"][0]

    row_ready = SimpleNamespace(p_mastery=0.8, mastery_confirmed=False)
    db = SimpleNamespace(execute=AsyncMock(return_value=_FakeResult(row_ready)))
    r = await gds.evaluate_return(db, "stu", session)
    assert r["ready"] is True and r["annotation"] == "刚补的就是这一步"
    assert r["next_action"] == "return_to_original"
    assert r["per_ku"][0]["ku_id"] == ku_id

    row_low = SimpleNamespace(p_mastery=0.3, mastery_confirmed=False)
    db2 = SimpleNamespace(execute=AsyncMock(return_value=_FakeResult(row_low)))
    r2 = await gds.evaluate_return(db2, "stu", session)
    assert r2["ready"] is False and r2["annotation"] is None

    row_none = None
    db3 = SimpleNamespace(execute=AsyncMock(return_value=_FakeResult(row_none)))
    r3 = await gds.evaluate_return(db3, "stu", session)
    assert r3["ready"] is False and r3["per_ku"][0]["p_mastery"] is None
