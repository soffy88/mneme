"""DoD 全闭环 e2e（capstone）——按 MCP 工具序列驱动 3 桩广东真 KC 跑到 complete。

- 建 path 校验（build_path）：ku004 有 rubric → 通过（防活锁，V12 的正路径）。
- 量化桩（solve/choice）：反复答对 → 既有 process_interaction → kc_mastery 下界过门。
- 定性桩（ku004 rubric）：submit(open)→needs_qualitative → **经真 qualitative_verifier
  （注入伪 LLMCaller）产出裁决 + evidence_spans** → ReportResult(llm_verified) →
  gate.qualitative_mastery。真 provider 绑定留 W2。

真 DB 写入；单 session 不 commit，退出回滚。需 mneme_core（②-0）。
"""

from __future__ import annotations

import json
import uuid

import pytest

pytest.importorskip("mneme_core")

from sqlalchemy import select, text  # noqa: E402

from mneme_core.oprim.models import KpView, Rubric  # noqa: E402
from mneme_core.oskill.qualitative_verifier import qualitative_verifier  # noqa: E402

from obase.db import SessionLocal  # noqa: E402
from services import gate_store  # noqa: E402
from services.mcp_router import (  # noqa: E402
    tool_check_mastery,
    tool_next_objective,
    tool_pose_question,
    tool_report_result,
    tool_submit_answer,
)
from services.models import KCMastery, User, UserRole  # noqa: E402
from services.path_builder import build_path  # noqa: E402

PROC_KC = "renjiao-math-g10-a-ku-二次函数的零点"
MEM_KC = "renjiao-math-g10-a-ku-三角函数的定义-单位圆"
CONCEPT_KC = "renjiao-math-g10-a-ku004"
KC_IDS = [PROC_KC, MEM_KC, CONCEPT_KC]

# 定性桩答案：刻意含四维 rubric 各自的可锚定原文子串（供伪 caller 引证）。
CONCEPT_ANSWER = (
    "函数是两个非空数集间的对应关系，每个 x 唯一对应一个 y；"
    "它由定义域、对应法则、值域三要素确定；"
    "可用解析法、列表法、图象法表示；若一对多则不构成函数。"
)
# 各 rubric 维度 → 该答案中的一个精确子串（伪 LLM 的引证）。
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
        "prompt": "单位圆上角α终边与…（选项）",
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
MAX_ITERS = 80


async def _verifier_evidence(db, kc: str, answer: str) -> dict:
    """经真 qualitative_verifier（注入伪 LLMCaller）产出 evidence，供 ReportResult。

    伪 caller 对每个 rubric 维度返回 passed + 锚定到 answer 原文的 span；元素内部做
    权重校验 + 幻觉回验。真 provider 绑定留 W2。
    """
    rubric = Rubric.from_dict(await gate_store.get_rubric(db, kc))
    kp = KpView(kc_id=kc, name="函数的概念与表示", gate_type="qualitative")

    def fake(*, messages):
        dims = []
        for d in rubric.dimensions:
            q = _DIM_QUOTES[d.name]
            i = answer.index(q)
            dims.append(
                {
                    "name": d.name,
                    "passed": True,
                    "spans": [{"start": i, "end": i + len(q), "quote": q}],
                }
            )
        return json.dumps({"dimensions": dims}, ensure_ascii=False)

    verdict = qualitative_verifier(answer, rubric=rubric, kp=kp, llm=fake)
    assert verdict.passed is True, verdict  # 四维全过 + 全部 span 回验通过
    return verdict.to_evidence()


async def _drive(db, sid) -> int:
    # 建 path 校验：qualitative KC(ku004) 必须有 rubric，否则活锁（此处通过）。
    await build_path(db, KC_IDS)

    for it in range(MAX_ITERS):
        step = await tool_next_objective(db, sid, KC_IDS)
        if step["action"] == "complete":
            return it
        kc = step["kc_id"]
        spec = SPECS[kc]
        qid = f"q-{uuid.uuid4().hex}"
        await tool_pose_question(
            db,
            student_id=sid,
            kc_id=kc,
            question_id=qid,
            prompt=spec["prompt"],
            expected=spec["expected"],
            qtype=spec["qtype"],
        )
        if spec["gate"] == "qualitative":
            r = await tool_submit_answer(
                db, student_id=sid, question_id=qid, answer=spec["answer"]
            )
            assert r.get("needs_qualitative") is True
            evidence = await _verifier_evidence(db, kc, spec["answer"])
            await tool_report_result(
                db,
                student_id=sid,
                kc_id=kc,
                question_id=qid,
                is_correct=True,
                verdict_source="llm_verified",
                evidence=evidence,
                model_id="fake-llm-w1",
            )
        else:
            r = await tool_submit_answer(
                db, student_id=sid, question_id=qid, answer=spec["answer"]
            )
            assert r["graded"] is True and r["is_correct"] is True
    raise AssertionError(f"未在 {MAX_ITERS} 轮内收敛到 complete")


@pytest.mark.asyncio
async def test_dod_full_loop_reaches_complete_all_mastered():
    async with SessionLocal() as db:
        sid = uuid.uuid4()
        db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
        await db.flush()

        iters = await _drive(db, sid)
        assert iters < MAX_ITERS

        # 三桩全 mastered
        for kc in KC_IDS:
            m = await tool_check_mastery(db, sid, kc)
            assert m["is_mastered"] is True, (kc, m)

        # 真 DB 写入：量化桩 kc_mastery 建卡；定性桩 gate.qualitative_mastery
        for kc in (PROC_KC, MEM_KC):
            row = (
                await db.execute(
                    select(KCMastery).where(
                        KCMastery.student_id == sid,
                        KCMastery.knowledge_point == kc,
                    )
                )
            ).scalar_one_or_none()
            assert row is not None and row.p_mastery is not None
        qmap = await gate_store.get_qualitative_mastery_map(db, sid)
        assert qmap.get(CONCEPT_KC) is True

        # evidence 落库：定性桩的 llm_verified 裁决可查，且含回验过的 evidence_spans
        ev_rows = (
            await db.execute(
                text(
                    "SELECT verdict FROM gate.evidence "
                    "WHERE student_id = CAST(:sid AS uuid) AND kc_id = :kc"
                ),
                {"sid": str(sid), "kc": CONCEPT_KC},
            )
        ).all()
        assert ev_rows, "定性桩 evidence 未落 gate.evidence"
        verdict = ev_rows[0][0]
        spans = [s for d in verdict["dimensions"] for s in d["spans"]]
        assert spans, "evidence 无 evidence_spans（锚定丢失）"
