"""D2.2 net rule + D1 rubric read path — 对着真 gate.* schema 验证。

依赖 Alembic 迁移 c4d5e6f7a8b9 已 upgrade（gate schema + ku004 rubric 种子）。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from obase.db import SessionLocal
from services.gate_store import (
    QUALITATIVE,
    QUANTITATIVE,
    clear_pending,
    get_pending,
    get_qualitative_mastery_map,
    get_rubric,
    pose_question,
    resolve_gate_type,
    save_evidence,
    upsert_qualitative_mastery,
)

KU004 = "renjiao-math-g10-a-ku004"  # DoD 定性桩：函数的概念与表示（已种 rubric）


@pytest.mark.asyncio
async def test_kc_with_intent_is_qualitative():
    """意图表命中的 KC → gate_type=qualitative；rubric 仍可读（判据，4 维、权重和=1）。"""
    async with SessionLocal() as db:
        assert await resolve_gate_type(db, KU004) == QUALITATIVE  # 经 intent 表
        rubric = await get_rubric(db, KU004)  # rubric 仅供判据
        assert rubric is not None
        dims = rubric["dimensions"]
        assert len(dims) == 4
        assert abs(sum(d["weight"] for d in dims) - 1.0) < 1e-9
        assert rubric["author"] == "handwritten"


@pytest.mark.asyncio
async def test_kc_without_intent_is_quantitative():
    """无意图记录的 KC → gate_type=quantitative，且 get_rubric 返回 None（fail-safe）。"""
    async with SessionLocal() as db:
        unknown = "no-such-kc-zzz"
        assert await resolve_gate_type(db, unknown) == QUANTITATIVE
        assert await get_rubric(db, unknown) is None


@pytest.mark.asyncio
async def test_intent_resolution_decoupled_from_rubric():
    """R2 §5 两层解析（M1：意图与判据分表）：intent 命中 > 默认 quantitative。

    - ku004 在 intent 表 → qualitative。
    - 无 intent 的数学 concept → default quantitative。
    - 现场写 **intent** → 翻为 qualitative（intent 驱动，非 rubric）。
    - 只写 **rubric**、不写 intent → **仍 quantitative**（M1 关键：rubric 只供判据、
      不再承载意图；这正是塌缩规则下不成立的解耦）。session 回滚，不污染库。
    """
    math_concept = "renjiao-math-g10-a-ku-二次函数的零点"
    other = "renjiao-math-g10-a-ku-三角函数的定义-单位圆"
    async with SessionLocal() as db:
        assert await resolve_gate_type(db, KU004) == QUALITATIVE
        assert await resolve_gate_type(db, math_concept) == QUANTITATIVE

        # 写 intent → 翻为 qualitative（意图驱动）
        await db.execute(
            text(
                "INSERT INTO gate.qualitative_intent (kc_id, reason, author) "
                "VALUES (:kc, 'test', 'test')"
            ),
            {"kc": math_concept},
        )
        assert await resolve_gate_type(db, math_concept) == QUALITATIVE

        # 只写 rubric、不写 intent → 仍 quantitative（解耦：rubric 不驱动 gate_type）
        await db.execute(
            text(
                "INSERT INTO gate.rubric (kc_id, dimensions, author) "
                "VALUES (:kc, CAST(:dim AS jsonb), 'test')"
            ),
            {"kc": other, "dim": '[{"name":"x","criterion":"c","weight":1.0}]'},
        )
        assert await resolve_gate_type(db, other) == QUANTITATIVE


@pytest.mark.asyncio
async def test_qualitative_mastery_map_empty_for_fresh_student():
    """无定性过门记录的学生 → 空 map（不报错）。"""
    async with SessionLocal() as db:
        got = await get_qualitative_mastery_map(db, uuid.uuid4())
        assert got == {}


# ── 写路径（切片②-1）——单 session 不 commit，退出自动回滚清理 ──────────────


@pytest.mark.asyncio
async def test_pose_get_clear_pending_roundtrip():
    """pose → get（含 expected）→ clear → get None。"""
    sid = uuid.uuid4()
    qid = f"q-{uuid.uuid4().hex}"
    async with SessionLocal() as db:
        await pose_question(
            db,
            question_id=qid,
            student_id=sid,
            kc_id="kc-x",
            prompt="求 x",
            expected="2",
            qtype="fill",
        )
        row = await get_pending(db, student_id=sid, question_id=qid)
        assert row is not None
        assert row["expected"] == "2" and row["qtype"] == "fill"

        await clear_pending(db, student_id=sid, question_id=qid)
        assert await get_pending(db, student_id=sid, question_id=qid) is None


@pytest.mark.asyncio
async def test_get_pending_scoped_to_student():
    """别的学生拿不到这道 pending（student_id 作用域）。"""
    qid = f"q-{uuid.uuid4().hex}"
    owner, other = uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as db:
        await pose_question(
            db,
            question_id=qid,
            student_id=owner,
            kc_id="kc-x",
            prompt="p",
            expected="e",
            qtype="choice",
        )
        assert await get_pending(db, student_id=other, question_id=qid) is None


@pytest.mark.asyncio
async def test_evidence_and_qualitative_upsert():
    """save_evidence + upsert_qualitative_mastery → map 反映 passed；再 upsert 覆盖。"""
    sid = uuid.uuid4()
    kc = "kc-concept-x"
    ref = uuid.uuid4().hex
    async with SessionLocal() as db:
        got_ref = await save_evidence(
            db,
            evidence_ref=ref,
            student_id=sid,
            kc_id=kc,
            verdict={"passed": True, "spans": [[0, 5, "对应关系本质"]]},
            model_id="qwen-max",
        )
        assert got_ref == ref

        await upsert_qualitative_mastery(
            db,
            student_id=sid,
            kc_id=kc,
            passed=True,
            evidence_ref=ref,
        )
        assert (await get_qualitative_mastery_map(db, sid)).get(kc) is True

        # 再次 upsert 覆盖为 False（幂等 upsert）
        await upsert_qualitative_mastery(
            db,
            student_id=sid,
            kc_id=kc,
            passed=False,
            evidence_ref=None,
        )
        assert (await get_qualitative_mastery_map(db, sid)).get(kc) is False
