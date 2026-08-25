"""GetPath —— 按学生档案派生学习路径（AA.5）。

对真实已装教材 renjiao-math-g10-a 断言：路径非空、只含"有内容"KC、按章节序（起点是集合
类基础，非高阶应用）。派生式路径无需 seed；跨会话确定性稳定。
"""

from __future__ import annotations

import uuid

import pytest

from obase.db import SessionLocal
from services.mcp_router import (
    DEFAULT_TEXTBOOK,
    _CONTENT_KC_SQL,
    tool_get_path,
)
from services.models import (
    KnowledgeCluster,
    KnowledgeUnit,
    Textbook,
    WrongQuestion,
)


@pytest.fixture
async def g10a_path_baseline():
    """自包含 GetPath 夹具：tool_get_path 需要 g10-a 教材里有“有内容”的 KU。
    这里种：教材 + 首章 cluster（display_order=1，集合类）+ 一个 id 含“集合”的 KU
    + 一道能过题库过滤的选择题（让该 KU “有内容”）。起点 KU 排在最前且 id 含“集合”，
    满足“起点是集合类基础”断言。测完即清，不污染共享库。

    KU 一律 verified=False，避免串到 test_daily_plan 的 P4 verified 优先过滤。
    """
    import uuid as _uuid

    from sqlalchemy import delete

    tb_id = DEFAULT_TEXTBOOK  # renjiao-math-g10-a
    c_id = "renjiao-math-g10-a-c01"
    ku_id = "renjiao-math-g10-a-ku-集合的概念"
    wq_id = _uuid.uuid4()
    created_textbook = False
    created_cluster = False
    created_ku = False

    async def _exists(db, model, pk):
        from sqlalchemy import select

        return (
            await db.execute(select(model.id).where(model.id == pk))
        ).first() is not None

    async with SessionLocal() as db:
        if not await _exists(db, Textbook, tb_id):
            db.add(
                Textbook(
                    id=tb_id,
                    subject="math",
                    grade="高一",
                    edition="2017修订",
                    book_name="人教版·高中数学必修一（A版）",
                )
            )
            created_textbook = True
            await db.flush()
        if not await _exists(db, KnowledgeCluster, c_id):
            db.add(
                KnowledgeCluster(
                    id=c_id,
                    textbook_id=tb_id,
                    name="集合与常用逻辑用语",
                    display_order=1,
                )
            )
            created_cluster = True
            await db.flush()
        if not await _exists(db, KnowledgeUnit, ku_id):
            db.add(
                KnowledgeUnit(
                    id=ku_id,
                    textbook_id=tb_id,
                    cluster_id=c_id,
                    name="集合的概念",
                    description="集合的含义与表示",
                    difficulty=0.3,
                    exam_frequency="high",
                    ku_type="concept",
                    verified=False,
                )
            )
            created_ku = True
        # 题库题：让该 KU “有内容”（过 tool_request_question 同款过滤）
        db.add(
            WrongQuestion(
                id=wq_id,
                student_id=None,
                subject="math",
                question_text="下列能构成集合的是？",
                correct_answer="A",
                knowledge_points={ku_id: "集合"},
                needs_image=False,
                profiler_analysis={
                    "grade": "高一",
                    "options": "A. 所有正整数\nB. 比较大的数\nC. 接近 0 的数\nD. 漂亮的图形",
                },
            )
        )
        await db.commit()

    yield {"textbook_id": tb_id, "ku_id": ku_id}

    async with SessionLocal() as db:
        await db.execute(
            delete(WrongQuestion).where(WrongQuestion.id == wq_id)
        )
        if created_ku:
            await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.id == ku_id))
        if created_cluster:
            await db.execute(delete(KnowledgeCluster).where(KnowledgeCluster.id == c_id))
        if created_textbook:
            await db.execute(delete(Textbook).where(Textbook.id == tb_id))
        await db.commit()


@pytest.mark.asyncio
async def test_get_path_content_filtered_and_ordered(g10a_path_baseline):
    async with SessionLocal() as db:
        p = await tool_get_path(db, uuid.uuid4())
        assert p["textbook_id"] == DEFAULT_TEXTBOOK
        kc = p["kc_ids"]
        assert len(kc) > 0, "路径不应为空（g10-a 已装内容）"

        # 只含"有内容"的 KC（题库自足题 或 rubric）—— 不会撞到无内容/占位题
        content = {r[0] for r in (await db.execute(_CONTENT_KC_SQL)).all() if r[0]}
        assert set(kc).issubset(content)

        # 章节序：起点是集合类基础（display_order 最前），不是高阶应用
        assert ("集合" in kc[0]) or ("数集" in kc[0]), (
            f"起点应为集合类基础，实得 {kc[0]}"
        )

        # 无重复
        assert len(kc) == len(set(kc))
