"""W3 A5 验收：SearchTextbookKnowledge（Mneme 自建 Knowledge Hub）返回带出处结果。

覆盖 kc_id 路径（走 A3 预计算的 ku_chunk_matches）和 free_text 路径（实时 embed +
全库 cosine）。断言：返回全部候选（非只 rank-1）、每条带 score、
provenance 硬编码为 "inferred"（不伪装权威）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text as sa_text

from obase.db import SessionLocal
from services.knowledge_hub_search import citation_state, search_knowledge_base


@pytest.mark.asyncio
async def test_search_by_kc_id_returns_top3_with_provenance_and_scores():
    async with SessionLocal() as db:
        # 取一个真实已挂接的 KU（A3 批量跑过，ku_chunk_matches 应有数据）
        row = (
            await db.execute(sa_text("SELECT ku_id FROM ku_chunk_matches LIMIT 1"))
        ).fetchone()
        assert row is not None, "ku_chunk_matches 为空——先跑 A3 批量挂接"
        kc_id = row[0]

        result = await search_knowledge_base(db, kc_id=kc_id, top_k=3)

    assert result["query_type"] == "kc_id"
    assert len(result["results"]) == 3
    ranks = [r["rank"] for r in result["results"]]
    assert ranks == [1, 2, 3]
    scores = [r["score"] for r in result["results"]]
    assert scores == sorted(scores, reverse=True)  # rank 1 分数最高
    for r in result["results"]:
        assert r["provenance"] == "inferred"
        assert isinstance(r["score"], float)
        assert r["chunk_id"]
        assert r["pdf_id"]
        assert "textbook_meta" in r


@pytest.mark.asyncio
async def test_search_by_free_text_returns_scored_inferred_results():
    async with SessionLocal() as db:
        result = await search_knowledge_base(db, query="等差数列的通项公式", top_k=3)

    assert result["query_type"] == "free_text"
    assert len(result["results"]) <= 3
    if result["results"]:
        for r in result["results"]:
            assert r["provenance"] == "inferred"
            assert isinstance(r["score"], float)
        scores = [r["score"] for r in result["results"]]
        assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_search_with_neither_kc_id_nor_query_returns_empty_not_error():
    async with SessionLocal() as db:
        result = await search_knowledge_base(db)

    assert result["results"] == []


@pytest.mark.asyncio
async def test_search_by_unknown_kc_id_returns_empty_not_error():
    async with SessionLocal() as db:
        result = await search_knowledge_base(db, kc_id="does-not-exist-xyz")

    assert result["query_type"] == "kc_id"
    assert result["results"] == []


@pytest.mark.asyncio
async def test_min_score_filters_out_low_confidence_matches():
    """Part B spec R1：挂接分 < 阈值不返回（垃圾兜底，见 knowledge_hub_search.py
    模块顶部——不宣称这保证正确，只是滤掉最明显的）。
    """
    async with SessionLocal() as db:
        row = (
            await db.execute(sa_text("SELECT ku_id FROM ku_chunk_matches LIMIT 1"))
        ).fetchone()
        kc_id = row[0]

        unfiltered = await search_knowledge_base(
            db, kc_id=kc_id, top_k=3, min_score=0.0
        )
        filtered = await search_knowledge_base(
            db, kc_id=kc_id, top_k=3, min_score=0.999
        )

    assert len(unfiltered["results"]) == 3
    assert len(filtered["results"]) == 0  # 0.999 高于任何真实 cosine 分数


@pytest.mark.asyncio
async def test_every_result_carries_verified_field_and_citation_state():
    """R3/R4：每条结果必须带 verified 字段，citation_state() 据此二态映射，
    不分高低分——见 knowledge_hub_search.py 顶部关于 0.732 也可能是错的说明。
    """
    async with SessionLocal() as db:
        row = (
            await db.execute(sa_text("SELECT ku_id FROM ku_chunk_matches LIMIT 1"))
        ).fetchone()
        result = await search_knowledge_base(db, kc_id=row[0], top_k=3)

    for r in result["results"]:
        assert "verified" in r
        assert isinstance(r["verified"], bool)
        assert citation_state(r) in ("verified", "inferred_unverified")
        assert citation_state(r) == (
            "verified" if r["verified"] else "inferred_unverified"
        )


@pytest.mark.asyncio
async def test_free_text_results_are_always_unverified():
    """free_text 路径不经 KU 挂接人工校订机制，恒为 unverified。"""
    async with SessionLocal() as db:
        result = await search_knowledge_base(db, query="等差数列的通项公式", top_k=3)

    for r in result["results"]:
        assert r["verified"] is False
        assert citation_state(r) == "inferred_unverified"
