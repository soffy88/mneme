"""GenerateQuiz —— 组卷（C2/W2C）：选 KC + 难度序列，不选具体题、不判分。

对真实已装教材 renjiao-math-g10-a 断言。派生式，无需写库；用随机 student_id
（无掌握度记录）即可验证选择/排序逻辑，不污染库。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from obase.db import SessionLocal
from services.mcp_router import tool_generate_quiz, tool_get_path
from services.models import KnowledgeUnit


@pytest.mark.asyncio
async def test_generate_quiz_default_pool_is_path_subset_capped_at_size():
    async with SessionLocal() as db:
        sid = uuid.uuid4()
        path = await tool_get_path(db, sid)
        result = await tool_generate_quiz(db, sid, size=5)

        assert result["size"] == len(result["kc_sequence"])
        assert result["size"] <= 5
        assert set(result["kc_sequence"]).issubset(set(path["kc_ids"]))
        assert len(result["kc_sequence"]) == len(set(result["kc_sequence"]))  # 无重复


@pytest.mark.asyncio
async def test_generate_quiz_explicit_kc_ids_respected():
    async with SessionLocal() as db:
        sid = uuid.uuid4()
        path = await tool_get_path(db, sid)
        subset = path["kc_ids"][:3]

        result = await tool_generate_quiz(db, sid, kc_ids=subset, size=10)
        assert set(result["kc_sequence"]).issubset(set(subset))


@pytest.mark.asyncio
async def test_generate_quiz_ascending_curve_matches_real_difficulty():
    async with SessionLocal() as db:
        sid = uuid.uuid4()
        path = await tool_get_path(db, sid)
        subset = path["kc_ids"][:6]

        result = await tool_generate_quiz(
            db, sid, kc_ids=subset, size=6, difficulty_curve="ascending"
        )

        rows = (
            await db.execute(
                select(KnowledgeUnit.id, KnowledgeUnit.difficulty).where(
                    KnowledgeUnit.id.in_(result["kc_sequence"])
                )
            )
        ).all()
        by_id = {r.id: r.difficulty for r in rows}
        difficulties = [by_id[kc] for kc in result["kc_sequence"]]
        assert difficulties == sorted(difficulties)


@pytest.mark.asyncio
async def test_generate_quiz_new_student_excludes_nothing_no_mastery_yet():
    """无掌握度记录的新学生：exclude_mastered 默认值不应误删任何候选（无 is_mastered 可判）。"""
    async with SessionLocal() as db:
        sid = uuid.uuid4()
        path = await tool_get_path(db, sid)
        subset = path["kc_ids"][:4]

        result = await tool_generate_quiz(db, sid, kc_ids=subset, size=10)
        assert set(result["kc_sequence"]) == set(subset)
