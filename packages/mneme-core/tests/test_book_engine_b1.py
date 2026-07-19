"""Tests for book_ideation / book_spine / book_page_plan (W3 Part B B1).

All tests inject a scripted fake async LLMCaller — zero provider dependency,
same convention as test_qualitative_verifier.py (sync there, async here since
real providers in this codebase are async).
"""

from __future__ import annotations

import json

import pytest

from mneme_core.oprim.models import (
    BookBlockType,
    BookContentType,
    BookProposal,
    ChapterSpec,
    ClusterSummary,
    TextbookMeta,
)
from mneme_core.oskill.book_ideation import book_ideation
from mneme_core.oskill.book_page_plan import book_page_plan
from mneme_core.oskill.book_spine import book_spine

META = TextbookMeta(
    textbook_id="RENJIAO-G8-MATH-S",
    subject="math",
    grade="G8",
    book_name="人教版·数学八年级上册",
)

CLUSTERS = [
    ClusterSummary(
        cluster_id="c1",
        name="三角形的基本概念与分类",
        display_order=1,
        ku_count=5,
        ku_names_sample=["三角形定义", "三角形分类"],
    ),
    ClusterSummary(
        cluster_id="c2",
        name="三角形的概念与分类",
        display_order=10,
        ku_count=4,
        ku_names_sample=["三角形定义", "按边分类"],
    ),
    ClusterSummary(
        cluster_id="c3",
        name="轴对称的基本概念与性质",
        display_order=5,
        ku_count=6,
        ku_names_sample=["轴对称定义", "对称轴"],
    ),
]


def _caller(payload):
    """Fake async LLMCaller: dict -> {"content": json}, str -> {"content": raw}."""

    async def call(*, messages, system=None, max_tokens=800):
        assert isinstance(messages, list) and messages
        content = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False)
        )
        return {"content": content}

    return call


def _raising_caller():
    async def call(*, messages, system=None, max_tokens=800):
        raise RuntimeError("provider down")

    return call


# ── book_ideation ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ideation_happy_path():
    llm = _caller(
        {
            "title": "三角形与轴对称",
            "description": "覆盖三角形性质与轴对称的活书",
            "scope": "人教版数学八年级上册",
            "target_level": "G8",
            "estimated_chapters": 5,
            "rationale": "合并重复聚类后估计 5 章",
        }
    )
    proposal = await book_ideation(llm, meta=META, clusters=CLUSTERS)
    assert proposal.title == "三角形与轴对称"
    assert proposal.estimated_chapters == 5
    assert proposal.textbook_id == META.textbook_id


@pytest.mark.asyncio
async def test_ideation_falls_back_on_malformed_json():
    llm = _caller("not json at all")
    proposal = await book_ideation(llm, meta=META, clusters=CLUSTERS)
    assert proposal.title  # 兜底仍产出非空标题
    assert proposal.textbook_id == META.textbook_id
    assert "兜底" in proposal.rationale


@pytest.mark.asyncio
async def test_ideation_falls_back_on_provider_exception():
    proposal = await book_ideation(_raising_caller(), meta=META, clusters=CLUSTERS)
    assert proposal.title
    assert proposal.estimated_chapters >= 1


# ── book_spine ───────────────────────────────────────────────────────────────


PROPOSAL = BookProposal(
    textbook_id=META.textbook_id,
    title="三角形与轴对称",
    estimated_chapters=2,
)


@pytest.mark.asyncio
async def test_spine_merges_duplicate_clusters_and_keeps_real_cluster_ids():
    """c1 和 c2 都是"三角形的...分类"，LLM 应该能合并成一章——这里验证的是
    校验逻辑本身：即便 LLM 把两个 cluster_id 都塞进一章，也必须都是真实存在的。
    """
    llm = _caller(
        {
            "chapters": [
                {
                    "title": "三角形基础",
                    "content_type": "theory",
                    "learning_objectives": ["理解三角形定义与分类"],
                    "cluster_ids": ["c1", "c2"],
                    "prerequisites": [],
                    "summary": "合并两个重复聚类",
                },
                {
                    "title": "轴对称",
                    "content_type": "concept",
                    "cluster_ids": ["c3"],
                    "prerequisites": ["三角形基础"],
                    "summary": "轴对称性质",
                },
            ]
        }
    )
    spine = await book_spine(llm, book_id="bk1", proposal=PROPOSAL, clusters=CLUSTERS)
    assert len(spine.chapters) == 2
    assert set(spine.chapters[0].cluster_ids) == {"c1", "c2"}
    assert spine.chapters[1].prerequisites == ["三角形基础"]


@pytest.mark.asyncio
async def test_spine_drops_chapter_with_fabricated_cluster_id():
    """LLM 编造了一个不存在的 cluster_id (c999) —— 该章必须被丢弃，不能让
    伪造出处混进章节树。
    """
    llm = _caller(
        {
            "chapters": [
                {"title": "真实章节", "cluster_ids": ["c1"], "content_type": "theory"},
                {
                    "title": "编造章节",
                    "cluster_ids": ["c999"],
                    "content_type": "theory",
                },
            ]
        }
    )
    spine = await book_spine(llm, book_id="bk1", proposal=PROPOSAL, clusters=CLUSTERS)
    titles = [c.title for c in spine.chapters]
    assert "真实章节" in titles
    assert "编造章节" not in titles


@pytest.mark.asyncio
async def test_spine_falls_back_to_1to1_cluster_mapping_on_parse_failure():
    spine = await book_spine(
        _raising_caller(), book_id="bk1", proposal=PROPOSAL, clusters=CLUSTERS
    )
    assert len(spine.chapters) == len(CLUSTERS)
    all_cluster_ids = {cid for ch in spine.chapters for cid in ch.cluster_ids}
    assert all_cluster_ids == {c.cluster_id for c in CLUSTERS}


# ── book_page_plan ───────────────────────────────────────────────────────────


CHAPTER = ChapterSpec(
    id="ch1",
    title="三角形基础",
    content_type=BookContentType.THEORY,
    learning_objectives=["理解三角形定义"],
    cluster_ids=["c1"],
)


@pytest.mark.asyncio
async def test_page_plan_llm_happy_path():
    llm = _caller(
        {
            "blocks": [
                {"type": "text", "params": {"role": "intro"}},
                {"type": "quiz", "params": {"num_questions": 2}},
                {"type": "guided", "params": {}},
            ]
        }
    )
    blocks = await book_page_plan(llm, chapter=CHAPTER)
    assert [b.type for b in blocks] == [
        BookBlockType.TEXT,
        BookBlockType.QUIZ,
        BookBlockType.GUIDED,
    ]


@pytest.mark.asyncio
async def test_page_plan_falls_back_to_static_template_when_llm_disabled():
    blocks = await book_page_plan(
        _caller({"blocks": []}), chapter=CHAPTER, llm_enabled=False
    )
    assert any(b.type == BookBlockType.TEXT for b in blocks)
    assert len(blocks) >= 4


@pytest.mark.asyncio
async def test_page_plan_falls_back_when_llm_omits_text_block():
    """LLM 返回的块序里没有 text 块——静态兜底保证至少有讲解正文。"""
    llm = _caller({"blocks": [{"type": "quiz", "params": {}}]})
    blocks = await book_page_plan(llm, chapter=CHAPTER)
    assert any(b.type == BookBlockType.TEXT for b in blocks)


@pytest.mark.asyncio
async def test_page_plan_falls_back_on_provider_exception():
    blocks = await book_page_plan(_raising_caller(), chapter=CHAPTER)
    assert any(b.type == BookBlockType.TEXT for b in blocks)


@pytest.mark.asyncio
async def test_page_plan_static_templates_differ_by_content_type():
    theory_blocks = await book_page_plan(_raising_caller(), chapter=CHAPTER)
    practice_chapter = ChapterSpec(
        id="ch2", title="练习章", content_type=BookContentType.PRACTICE
    )
    practice_blocks = await book_page_plan(_raising_caller(), chapter=practice_chapter)
    assert [b.type for b in theory_blocks] != [b.type for b in practice_blocks]
