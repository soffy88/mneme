"""②-2 ProgressView 组装器 — 投影真相源 → mneme-core LearningProgress，并验证
纯库 is_mastered 在量化/定性两条路径上都吃到正确的 gate_type（决策 D2.2 端到端）。

单 session 不 commit，退出自动回滚清理。需 mneme_core 可 import（②-0 打包，测试经 PYTHONPATH）。
"""

from __future__ import annotations

import uuid

import pytest

# ②-0 打包前（镜像未装 mneme_core）整文件跳过，保全量 CI 绿；装好后自动生效。
pytest.importorskip("mneme_core")

from datetime import datetime, timezone  # noqa: E402

from mneme_core.oprim.mastery_gate import is_mastered, next_objective  # noqa: E402
from mneme_core.oprim.models import KnowledgeType, NextAction  # noqa: E402

from obase.db import SessionLocal  # noqa: E402
from services import gate_store  # noqa: E402
from services.models import (  # noqa: E402
    InteractionEvent,
    InteractionSource,
    KCMastery,
    User,
    UserRole,
)
from services.progress_assembler import build_learning_progress  # noqa: E402

KU004 = "renjiao-math-g10-a-ku004"  # 有 rubric → 定性桩
QUANT_KC = "renjiao-math-g10-a-ku-二次函数的零点"  # 无 rubric → 量化桩
MEM_KC = "renjiao-math-g10-a-ku-三角函数的定义-单位圆"  # 无 rubric → 量化桩


async def _seed_student(db, sid):
    db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
    await db.flush()  # 先落 user，满足 kc_mastery/interaction_events 的 FK
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
    for _ in range(3):  # n_obs = 3 ≥ N_MIN
        db.add(
            InteractionEvent(
                student_id=sid,
                knowledge_point=QUANT_KC,
                source=InteractionSource.paper,
                is_correct=True,
            )
        )
    await db.flush()


@pytest.mark.asyncio
async def test_gate_type_from_intent_presence():
    """意图命中的 KC(ku004) → CONCEPT(定性)；无意图 → PROCEDURE(量化)。R2 §5/M1。"""
    sid = uuid.uuid4()
    async with SessionLocal() as db:
        await _seed_student(db, sid)
        prog = await build_learning_progress(db, sid, [QUANT_KC, KU004])

        kps = {kp.id: kp for kp in prog.modules[0].knowledge_points}
        assert kps[QUANT_KC].type == KnowledgeType.PROCEDURE
        assert kps[KU004].type == KnowledgeType.CONCEPT


@pytest.mark.asyncio
async def test_quantitative_mastery_via_bkt_lower_bound():
    """量化桩：p=0.98、n_obs=3 → 下界过 0.9 门 → is_mastered True。"""
    sid = uuid.uuid4()
    async with SessionLocal() as db:
        await _seed_student(db, sid)
        prog = await build_learning_progress(db, sid, [QUANT_KC])
        kp = prog.modules[0].knowledge_points[0]

        assert prog.bkt[QUANT_KC].n_obs == 3
        assert prog.bkt[QUANT_KC].p_learned == pytest.approx(0.98)
        assert is_mastered(prog, kp) is True


@pytest.mark.asyncio
async def test_qualitative_mastery_via_gate_flag():
    """定性桩：ku004 有 rubric，gate.qualitative_mastery 决定过门（不看 bkt）。"""
    sid = uuid.uuid4()
    async with SessionLocal() as db:
        await _seed_student(db, sid)
        prog0 = await build_learning_progress(db, sid, [KU004])
        ku004_kp = prog0.modules[0].knowledge_points[0]
        # 未过门
        assert is_mastered(prog0, ku004_kp) is False

        # 写入定性过门 → 再组装 → mastered
        await gate_store.upsert_qualitative_mastery(
            db, student_id=sid, kc_id=KU004, passed=True, evidence_ref=None
        )
        prog1 = await build_learning_progress(db, sid, [KU004])
        assert is_mastered(prog1, prog1.modules[0].knowledge_points[0]) is True


@pytest.mark.asyncio
async def test_error_linked_review_prioritised():
    """V11：两量化 KC 同 due，有错误史且未 graduated 者提权 priority=1，NextObjective 先出它。"""
    past = "2020-01-01T00:00:00+00:00"  # 早于 now → 到期
    sid = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
        await db.flush()
        # 两个量化 KC（无 rubric），都到期、都未过门（低 p_mastery=0.5）
        for kc in (QUANT_KC, MEM_KC):
            db.add(
                KCMastery(
                    student_id=sid,
                    knowledge_point=kc,
                    p_mastery=0.5,
                    p_init=0.3,
                    p_transit=0.3,
                    p_guess=0.2,
                    p_slip=0.1,
                    fsrs_card_json={"due": past},
                )
            )
        # QUANT_KC 有错误史；MEM_KC 只有正确记录
        db.add(
            InteractionEvent(
                student_id=sid,
                knowledge_point=QUANT_KC,
                source=InteractionSource.paper,
                is_correct=False,
            )
        )
        db.add(
            InteractionEvent(
                student_id=sid,
                knowledge_point=MEM_KC,
                source=InteractionSource.paper,
                is_correct=True,
            )
        )
        await db.flush()

        prog = await build_learning_progress(db, sid, [MEM_KC, QUANT_KC])
        pri = {r.knowledge_point_id: r.priority for r in prog.review_queue}
        assert pri[QUANT_KC] == 1, pri  # error-linked 提权
        assert pri[MEM_KC] == 2, pri

        # NextObjective 到期优先 review，且先出 error-linked（priority 升序）
        step = next_objective(prog, now=datetime.now(timezone.utc).timestamp())
        assert step.action == NextAction.REVIEW
        assert step.kc_id == QUANT_KC


@pytest.mark.asyncio
async def test_graduated_error_kc_not_prioritised():
    """已 graduated（下界过门）的 KC 即便有错误史也不提权 → priority=2。"""
    past = "2020-01-01T00:00:00+00:00"
    sid = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
        await db.flush()
        db.add(
            KCMastery(
                student_id=sid,
                knowledge_point=QUANT_KC,
                p_mastery=0.98,
                p_init=0.3,
                p_transit=0.3,
                p_guess=0.2,
                p_slip=0.1,
                fsrs_card_json={"due": past},
            )
        )
        # 足够观测使下界过门（graduated），其中含一条错误
        db.add(
            InteractionEvent(
                student_id=sid,
                knowledge_point=QUANT_KC,
                source=InteractionSource.paper,
                is_correct=False,
            )
        )
        for _ in range(9):
            db.add(
                InteractionEvent(
                    student_id=sid,
                    knowledge_point=QUANT_KC,
                    source=InteractionSource.paper,
                    is_correct=True,
                )
            )
        await db.flush()

        prog = await build_learning_progress(db, sid, [QUANT_KC])
        pri = {r.knowledge_point_id: r.priority for r in prog.review_queue}
        assert pri[QUANT_KC] == 2, pri  # graduated → 不提权


@pytest.mark.asyncio
async def test_unlearned_quant_kc_not_mastered():
    """量化 KC 无 kc_mastery 行 → 无 bkt → 证据不足不过门。"""
    sid = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
        await db.flush()
        prog = await build_learning_progress(db, sid, [QUANT_KC])
        assert QUANT_KC not in prog.bkt
        assert is_mastered(prog, prog.modules[0].knowledge_points[0]) is False
