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
async def test_kc_with_rubric_is_qualitative():
    """有 rubric 的 KC → gate_type=qualitative，rubric 可读、4 维、权重和=1。"""
    async with SessionLocal() as db:
        assert await resolve_gate_type(db, KU004) == QUALITATIVE
        rubric = await get_rubric(db, KU004)
        assert rubric is not None
        dims = rubric["dimensions"]
        assert len(dims) == 4
        assert abs(sum(d["weight"] for d in dims) - 1.0) < 1e-9
        assert rubric["author"] == "handwritten"


@pytest.mark.asyncio
async def test_kc_without_rubric_is_quantitative():
    """无 rubric 的 KC → gate_type=quantitative，且 get_rubric 返回 None（fail-safe）。"""
    async with SessionLocal() as db:
        unknown = "no-such-kc-zzz"
        assert await resolve_gate_type(db, unknown) == QUANTITATIVE
        assert await get_rubric(db, unknown) is None


@pytest.mark.asyncio
async def test_override_resolution():
    """两层解析（A1 塌缩后）：override(rubric 存在) > default(quantitative)。

    - ku004 有 rubric → override 生效 → qualitative。
    - 无 rubric 的数学 concept → 落 default → quantitative。
    - 给一个本会 default 量化的 KC 现场写 rubric → 被 override 翻为 qualitative
      （override 胜 default）。session 回滚，不污染库。
    白名单层（第 2 层）随非数学科目于 W2 恢复（A1），W1 不参与。
    """
    math_concept = "renjiao-math-g10-a-ku-二次函数的零点"
    async with SessionLocal() as db:
        assert await resolve_gate_type(db, KU004) == QUALITATIVE  # override
        assert await resolve_gate_type(db, math_concept) == QUANTITATIVE  # default

        await db.execute(
            text(
                "INSERT INTO gate.rubric (kc_id, dimensions, author) "
                "VALUES (:kc, CAST(:dim AS jsonb), 'test')"
            ),
            {
                "kc": math_concept,
                "dim": '[{"name":"x","criterion":"c","weight":1.0}]',
            },
        )
        # override 现在命中 → 翻为 qualitative（证明 override 优先级高于 default）
        assert await resolve_gate_type(db, math_concept) == QUALITATIVE


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
