"""W3 A5 验收：SearchTextbookKnowledge（Mneme 自建 Knowledge Hub）返回带出处结果。

覆盖 kc_id 路径（走 A3 预计算的 ku_chunk_matches）和 free_text 路径（实时 embed +
全库 cosine）。断言：返回全部候选（非只 rank-1）、每条带 score、
provenance 硬编码为 "inferred"（不伪装权威）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text as sa_text

from obase.db import SessionLocal
from services.knowledge_hub_search import search_knowledge_base


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
