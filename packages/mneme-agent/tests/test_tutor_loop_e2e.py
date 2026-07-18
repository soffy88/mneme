"""W2a S2 W5 — 引擎驱动的 DoD 三桩 e2e（撤销 R2 A-7 的工具序列临时方案）。

真 oservi AgenticLoop.session() 多步循环驱动三桩广东真 KC 跑到 complete：
scripted llm_caller 读上一个 tool_result + 工具名 → 决定下一个 tool_use（ReAct）。
工具全走 HTTP /mcp/*（agent 零 DB）。定性桩经 AssessExplanation（真 qualitative_verifier
+ 注入伪 verifier_llm）→ ReportResult。**禁手写循环**：循环逻辑全在引擎 session。

harness（本测试）有 DB：建 pilot 学生 + 断言写入 + 清理；agent（tutor_loop）零 DB。
需 oservi（compose mount /opt/oservi_pkg）+ 运行中的 api（/mcp 活）。
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

pytest.importorskip("oservi")
pytest.importorskip("mneme_core")

from mneme_agent.assembly.tutor_loop import build_tutor_loop  # noqa: E402

API_BASE = "http://localhost:8000"

PROC_KC = "renjiao-math-g10-a-ku-二次函数的零点"
MEM_KC = "renjiao-math-g10-a-ku-三角函数的定义-单位圆"
CONCEPT_KC = "renjiao-math-g10-a-ku004"
KC_IDS = [PROC_KC, MEM_KC, CONCEPT_KC]

CONCEPT_ANSWER = (
    "函数是两个非空数集间的对应关系，每个 x 唯一对应一个 y；"
    "它由定义域、对应法则、值域三要素确定；"
    "可用解析法、列表法、图象法表示；若一对多则不构成函数。"
)
_DIM_QUOTES = {
    "对应关系本质": "对应关系",
    "三要素完整": "定义域、对应法则、值域三要素",
    "表示法辨识": "解析法、列表法、图象法",
    "反例判别": "一对多则不构成函数",
}
SPECS = {
    PROC_KC: {
        "qtype": "solve",
        "prompt": "解 x^2-5x+6=0",
        "expected": "x=2 或 x=3",
        "answer": "x=2, x=3",
        "gate": "quantitative",
    },
    MEM_KC: {
        "qtype": "choice",
        "prompt": "单位圆上角α…（选项）",
        "expected": "A",
        "answer": "A",
        "gate": "quantitative",
    },
    CONCEPT_KC: {
        "qtype": "open",
        "prompt": "请解释什么是函数",
        "expected": None,
        "answer": CONCEPT_ANSWER,
        "gate": "qualitative",
    },
}


def _tool_use(name, inp):
    return {
        "content": [
            {
                "type": "tool_use",
                "id": f"tu-{uuid.uuid4().hex[:8]}",
                "name": name,
                "input": inp,
            }
        ],
        "stop_reason": "tool_use",
        "usage": {},
    }


def _text(t):
    return {
        "content": [{"type": "text", "text": t}],
        "stop_reason": "end_turn",
        "usage": {},
    }


def _last_tool(messages):
    """从 messages 尾部取上一个 (工具名, 结果 dict)；无则 (None, None)。"""
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("role") == "user" and isinstance(m.get("content"), list):
            trs = [
                b
                for b in m["content"]
                if isinstance(b, dict) and b.get("type") == "tool_result"
            ]
            if trs:
                try:
                    result = json.loads(trs[0].get("content", "{}"))
                except (json.JSONDecodeError, TypeError):
                    result = {}
                # 前一条 assistant 里的 tool_use 名
                name = None
                for j in range(i - 1, -1, -1):
                    a = messages[j]
                    if a.get("role") == "assistant" and isinstance(
                        a.get("content"), list
                    ):
                        tus = [
                            b
                            for b in a["content"]
                            if isinstance(b, dict) and b.get("type") == "tool_use"
                        ]
                        if tus:
                            name = tus[0].get("name")
                            break
                return name, result
    return None, None


def _make_caller():
    """ReAct scripted caller：读上一个 tool_result 决定下一步。驱动三桩到 complete。"""
    st = {"qid": None, "kc": None}

    async def caller(
        messages, tools=None, max_tokens=None, thinking_budget=None, system=None
    ):
        last, res = _last_tool(messages)
        if last is None:
            return _tool_use("NextObjective", {})
        if last == "NextObjective":
            if res.get("action") == "complete":
                return _text("三桩全部 mastered")
            kc = res.get("kc_id")
            spec = SPECS[kc]
            st["kc"] = kc
            st["qid"] = f"q-{uuid.uuid4().hex}"
            return _tool_use(
                "PoseQuestion",
                {
                    "kc_id": kc,
                    "question_id": st["qid"],
                    "prompt": spec["prompt"],
                    "expected": spec["expected"],
                    "qtype": spec["qtype"],
                },
            )
        if last == "PoseQuestion":
            spec = SPECS[st["kc"]]
            return _tool_use(
                "SubmitAnswer", {"question_id": st["qid"], "answer": spec["answer"]}
            )
        if last == "SubmitAnswer":
            if res.get("needs_qualitative"):
                spec = SPECS[st["kc"]]
                return _tool_use(
                    "AssessExplanation",
                    {"kc_id": st["kc"], "explanation": spec["answer"]},
                )
            return _tool_use("NextObjective", {})
        if last == "AssessExplanation":
            return _tool_use(
                "ReportResult",
                {
                    "kc_id": st["kc"],
                    "question_id": st["qid"],
                    "is_correct": bool(res.get("passed")),
                    "verdict_source": "llm_verified",
                    "evidence": res.get("evidence"),
                    "model_id": "fake-llm-w1",
                },
            )
        if last == "ReportResult":
            return _tool_use("NextObjective", {})
        return _text("unexpected")

    return caller


def _make_verifier_llm():
    """伪 verifier_llm：对 CONCEPT 答案每维锚定一个原文子串（真 provider W2b）。"""

    def caller(*, messages):
        dims = []
        for name, q in _DIM_QUOTES.items():
            i = CONCEPT_ANSWER.index(q)
            dims.append(
                {
                    "name": name,
                    "passed": True,
                    "spans": [{"start": i, "end": i + len(q), "quote": q}],
                }
            )
        return json.dumps({"dimensions": dims}, ensure_ascii=False)

    return caller


@pytest.mark.asyncio
async def test_engine_driven_three_stakes_reach_complete():
    from sqlalchemy import text
    from obase.db import SessionLocal
    from services.models import User, UserRole

    from obase.auth import create_access_token

    sid = uuid.uuid4()
    async with SessionLocal() as db:  # harness 建 pilot（agent 零 DB）
        db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
        await db.commit()
    try:
        loop = build_tutor_loop(
            api_base=API_BASE,
            student_id=str(sid),
            kc_ids=KC_IDS,
            llm_caller=_make_caller(),
            verifier_llm=_make_verifier_llm(),
            # AA.1 起 /mcp/* 要求 JWT；harness 现铸该学生自己的 token 转发给工具调用。
            auth_token=create_access_token({"sub": str(sid)}),
            max_iterations=150,
        )
        result = await loop.session(task="帮我把这三条 KC 学到过门")

        assert result["status"] == "completed", result
        # 真 DB 写入（经 HTTP → process_interaction / gate.*）
        async with SessionLocal() as db:
            for kc in (PROC_KC, MEM_KC):
                row = (
                    await db.execute(
                        text(
                            "SELECT p_mastery, n_attempts FROM kc_mastery "
                            "WHERE student_id=:s AND knowledge_point=:k"
                        ),
                        {"s": str(sid), "k": kc},
                    )
                ).first()
                assert row is not None and row[0] is not None, (kc, "no kc_mastery")
                assert row[1] >= 2, (kc, "n_attempts", row[1])  # P2：重复作答
            qm = (
                await db.execute(
                    text(
                        "SELECT passed FROM gate.qualitative_mastery WHERE student_id=:s AND kc_id=:k"
                    ),
                    {"s": str(sid), "k": CONCEPT_KC},
                )
            ).first()
            assert qm is not None and qm[0] is True, "ku004 定性未过门"
            # 探针 P1：有答对
            corr = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM interaction_events WHERE student_id=:s AND is_correct"
                    ),
                    {"s": str(sid)},
                )
            ).scalar_one()
            assert corr >= 1, "P1: 无答对"
    finally:
        # 清理 pilot，保基线不被测试污染
        async with SessionLocal() as db:
            from services.models import User as U  # noqa

            await db.execute(
                text(
                    "UPDATE users SET deleted_at=now() - interval '1 day' WHERE id=:i"
                ),
                {"i": str(sid)},
            )
            await db.commit()
        async with SessionLocal() as db:
            from services.purge_service import purge_deleted_users

            await purge_deleted_users(db, grace_days=0)
            await db.commit()


if __name__ == "__main__":
    asyncio.run(test_engine_driven_three_stakes_reach_complete())
    print("OK")
