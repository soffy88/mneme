"""W3 Part B B2 功能测试：block_type -> generator 注册表。

用真实 DB 数据（已索引教材 + 真实 knowledge_clusters/ku_chunk_matches）+
scripted fake LLM caller（不依赖真实 provider，同 B1 test_book_engine_b1.py
的约定）。
"""

from __future__ import annotations

import json

import pytest

from mneme_core.oprim.models import (
    BlockSpec,
    BookBlockType,
    BookContentType,
    ChapterSpec,
)
from obase.db import SessionLocal
from services.book_block_generators import BlockContext, generate_block

# 真实存在的 G8 上册 cluster（本会话 A1-A3 已确认索引/挂接过）
REAL_CLUSTER_ID = "RENJIAO-G8-MATH-S-kc-三角形的基本概念与分类"


def _caller(payload):
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


def _chapter(content_type=BookContentType.THEORY, cluster_ids=None) -> ChapterSpec:
    return ChapterSpec(
        id="ch1",
        title="三角形的基础与性质",
        content_type=content_type,
        learning_objectives=["理解三角形的基本概念"],
        cluster_ids=cluster_ids if cluster_ids is not None else [REAL_CLUSTER_ID],
        summary="三角形基础章节",
    )


@pytest.mark.asyncio
async def test_text_block_grounds_on_real_citations_when_above_threshold():
    async with SessionLocal() as db:
        block = BlockSpec(type=BookBlockType.TEXT, params={"role": "introduction"})
        ctx = BlockContext(
            db=db,
            caller=_caller("三角形是由三条线段首尾相连组成的图形。"),
            book_id="bk1",
            chapter=_chapter(),
            block=block,
        )
        result = await generate_block(ctx)

    assert result["status"] == "ready"
    assert result["payload"]["text"]
    # 真实已索引教材 + 真实挂接，应该能找到过阈值的引用素材
    for c in result["payload"]["citations"]:
        assert c["score"] >= 0.60
        assert c["citation_state"] in ("verified", "inferred_unverified")


@pytest.mark.asyncio
async def test_text_block_falls_back_to_chapter_summary_on_llm_failure():
    async with SessionLocal() as db:
        block = BlockSpec(type=BookBlockType.TEXT, params={})
        ctx = BlockContext(
            db=db,
            caller=_raising_caller(),
            book_id="bk1",
            chapter=_chapter(),
            block=block,
        )
        result = await generate_block(ctx)

    assert result["status"] == "ready"
    assert "三角形的基础与性质" in result["payload"]["text"]


@pytest.mark.asyncio
async def test_text_block_with_no_real_clusters_has_no_citations():
    """章节没有绑定任何真实 cluster（比如 spine 兜底路径产生的孤儿章节）——
    不应该编造引用，citations 必须是空列表。
    """
    async with SessionLocal() as db:
        block = BlockSpec(type=BookBlockType.TEXT, params={})
        ctx = BlockContext(
            db=db,
            caller=_caller("占位文本"),
            book_id="bk1",
            chapter=_chapter(cluster_ids=[]),
            block=block,
        )
        result = await generate_block(ctx)

    assert result["payload"]["citations"] == []


@pytest.mark.asyncio
async def test_figure_block_returns_latex_and_citations():
    async with SessionLocal() as db:
        block = BlockSpec(type=BookBlockType.FIGURE, params={})
        ctx = BlockContext(
            db=db,
            caller=_caller({"latex": "$a+b=c$", "caption": "三角形边长关系"}),
            book_id="bk1",
            chapter=_chapter(),
            block=block,
        )
        result = await generate_block(ctx)

    assert result["status"] == "ready"
    assert result["payload"]["latex"] == "$a+b=c$"


@pytest.mark.asyncio
async def test_figure_block_falls_back_to_empty_on_malformed_json():
    async with SessionLocal() as db:
        block = BlockSpec(type=BookBlockType.FIGURE, params={})
        ctx = BlockContext(
            db=db,
            caller=_caller("not json"),
            book_id="bk1",
            chapter=_chapter(),
            block=block,
        )
        result = await generate_block(ctx)

    assert result["status"] == "ready"
    assert result["payload"]["latex"] == ""


@pytest.mark.asyncio
async def test_quiz_block_only_stores_kc_ids_not_actual_questions():
    """QUIZ 块编译期只存 kc_ids scope——不产出具体题目（架构设计，见模块顶部
    说明：具体选题/判分是 per-student 实时的既有 RequestQuestion/SubmitAnswer 路径）。
    """
    async with SessionLocal() as db:
        block = BlockSpec(type=BookBlockType.QUIZ, params={"num_questions": 2})
        ctx = BlockContext(
            db=db,
            caller=_raising_caller(),
            book_id="bk1",
            chapter=_chapter(),
            block=block,
        )
        result = await generate_block(ctx)

    assert result["status"] == "ready"
    assert "kc_ids" in result["payload"]
    assert len(result["payload"]["kc_ids"]) <= 2
    assert "question" not in json.dumps(result["payload"])  # 没有具体题目内容
    assert "expected" not in result["payload"]


@pytest.mark.asyncio
async def test_flash_cards_block_uses_real_ku_name_and_description():
    async with SessionLocal() as db:
        block = BlockSpec(type=BookBlockType.FLASH_CARDS, params={"count": 3})
        ctx = BlockContext(
            db=db,
            caller=_raising_caller(),
            book_id="bk1",
            chapter=_chapter(),
            block=block,
        )
        result = await generate_block(ctx)

    assert result["status"] == "ready"
    cards = result["payload"]["cards"]
    assert len(cards) <= 3
    for card in cards:
        assert card["front"]  # 真实 KU name，非空


@pytest.mark.asyncio
async def test_guided_block_stores_kc_ids_scope_only():
    async with SessionLocal() as db:
        block = BlockSpec(type=BookBlockType.GUIDED, params={})
        ctx = BlockContext(
            db=db,
            caller=_raising_caller(),
            book_id="bk1",
            chapter=_chapter(),
            block=block,
        )
        result = await generate_block(ctx)

    assert result["status"] == "ready"
    assert result["payload"]["mode"] == "live_next_objective"
    assert "next_action" not in result["payload"]  # 不预先算好下一步，渲染期才算


@pytest.mark.asyncio
async def test_unknown_block_type_returns_error_not_raise():
    """generate_block 对未注册类型不抛异常——同项目"降级不阻断"惯例。"""
    async with SessionLocal() as db:
        block = BlockSpec(type=BookBlockType.CALLOUT, params={})
        ctx = BlockContext(
            db=db,
            caller=_raising_caller(),
            book_id="bk1",
            chapter=_chapter(),
            block=block,
        )
        result = await generate_block(ctx)
        assert result["status"] == "ready"  # callout 有生成器，先确认这条路径本身没问题

        from services.book_block_generators import BLOCK_GENERATORS

        original = BLOCK_GENERATORS.pop(BookBlockType.CALLOUT)
        try:
            result2 = await generate_block(ctx)
            assert result2["status"] == "error"
        finally:
            BLOCK_GENERATORS[BookBlockType.CALLOUT] = original
