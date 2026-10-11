"""SearchKnowledgeBase —— C4（W2C）Stratum 检索 MCP 工具。假 rag_client（无真网络）。"""

from __future__ import annotations

import pytest

from services.mcp_router import tool_search_knowledge_base


@pytest.mark.asyncio
async def test_tool_search_knowledge_base_delegates_to_rag_client(monkeypatch):
    captured = {}

    async def fake_search(query, *, top_k=5):
        captured["query"] = query
        captured["top_k"] = top_k
        return [{"id": "1", "title": "函数的概念", "highlight": None, "score": 0.8}]

    monkeypatch.setattr("services.rag_client.search", fake_search)

    result = await tool_search_knowledge_base("函数", top_k=3)

    assert captured == {"query": "函数", "top_k": 3}
    assert result == {
        "results": [{"id": "1", "title": "函数的概念", "highlight": None, "score": 0.8}]
    }


@pytest.mark.asyncio
async def test_tool_search_knowledge_base_empty_when_stratum_unavailable(monkeypatch):
    async def fake_search(query, *, top_k=5):
        del query, top_k
        return []

    monkeypatch.setattr("services.rag_client.search", fake_search)

    result = await tool_search_knowledge_base("函数")
    assert result == {"results": []}


@pytest.mark.asyncio
async def test_tool_search_knowledge_base_falls_back_to_knowledge_hub_when_stratum_empty(
    monkeypatch,
):
    """2026-10：Stratum service 账号语料库为空 → 给了 db 时回落 Knowledge Hub。"""

    async def fake_search(query, *, top_k=5):
        del query, top_k
        return []

    captured = {}

    async def fake_hub(db, *, kc_id=None, query=None, top_k=3, min_score=0.0):
        captured.update(db=db, kc_id=kc_id, query=query, top_k=top_k)
        return {
            "query_type": "free_text",
            "results": [
                {
                    "chunk_id": "f1_00012",
                    "pdf_id": "f1",
                    "page_number": 24,
                    "char_start": 0,
                    "char_end": 20,
                    "content": "勾股定理：直角三角形两直角边的平方和等于斜边的平方。",
                    "textbook_meta": {
                        "subject": "math",
                        "grade": "G8",
                        "book_name": "人教版·数学八年级下册",
                    },
                    "score": 0.71,
                    "rank": 1,
                    "provenance": "inferred",
                    "verified": False,
                }
            ],
        }

    monkeypatch.setattr("services.rag_client.search", fake_search)
    monkeypatch.setattr(
        "services.knowledge_hub_search.search_knowledge_base", fake_hub
    )

    sentinel_db = object()
    result = await tool_search_knowledge_base("勾股定理", top_k=4, db=sentinel_db)

    assert captured == {"db": sentinel_db, "kc_id": None, "query": "勾股定理", "top_k": 4}
    assert result["source"] == "mneme_knowledge_hub"
    (item,) = result["results"]
    assert item["id"] == "f1_00012"
    assert item["title"] == "人教版·数学八年级下册 p.24"
    assert "勾股定理" in item["highlight"]
    assert item["score"] == 0.71
    assert item["provenance"] == "inferred"
    assert item["verified"] is False
    assert item["source"] == "mneme_knowledge_hub"


@pytest.mark.asyncio
async def test_tool_search_knowledge_base_prefers_stratum_results(monkeypatch):
    async def fake_search(query, *, top_k=5):
        del query, top_k
        return [{"id": "s1", "title": "函数", "highlight": None, "score": 0.9}]

    async def fake_hub(*a, **k):  # pragma: no cover - must not be called
        raise AssertionError("knowledge hub should not be queried")

    monkeypatch.setattr("services.rag_client.search", fake_search)
    monkeypatch.setattr(
        "services.knowledge_hub_search.search_knowledge_base", fake_hub
    )
    result = await tool_search_knowledge_base("函数", db=object())
    assert result == {
        "results": [{"id": "s1", "title": "函数", "highlight": None, "score": 0.9}]
    }


@pytest.mark.asyncio
async def test_tool_search_knowledge_base_hub_failure_is_fail_safe(monkeypatch):
    async def fake_search(query, *, top_k=5):
        del query, top_k
        return []

    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("services.rag_client.search", fake_search)
    monkeypatch.setattr("services.knowledge_hub_search.search_knowledge_base", boom)
    result = await tool_search_knowledge_base("函数", db=object())
    assert result == {"results": []}


@pytest.mark.asyncio
async def test_fallback_drops_semantic_hits_below_relevance_floor(monkeypatch):
    from services.mcp_router import KB_FALLBACK_MIN_COSINE

    async def fake_search(query, *, top_k=5):
        del query, top_k
        return []

    def _r(cid, score):
        return {
            "chunk_id": cid,
            "pdf_id": "f",
            "page_number": 1,
            "char_start": 0,
            "char_end": 1,
            "content": "c",
            "textbook_meta": {"subject": "math", "grade": "G1", "book_name": "B"},
            "score": score,
            "rank": 1,
            "provenance": "inferred",
            "verified": False,
        }

    async def fake_hub(db, **k):
        del db, k
        return {
            "query_type": "free_text",
            "results": [_r("hi", KB_FALLBACK_MIN_COSINE + 0.05), _r("lo", 0.40)],
        }

    monkeypatch.setattr("services.rag_client.search", fake_search)
    monkeypatch.setattr("services.knowledge_hub_search.search_knowledge_base", fake_hub)
    result = await tool_search_knowledge_base("光合作用", db=object())
    assert [i["id"] for i in result["results"]] == ["hi"]

    async def fake_hub_lex(db, **k):
        del db, k
        return {
            "query_type": "free_text",
            "retrieval": "lexical",
            "results": [_r("lex", 0.3)],
        }

    monkeypatch.setattr(
        "services.knowledge_hub_search.search_knowledge_base", fake_hub_lex
    )
    result = await tool_search_knowledge_base("光合作用", db=object())
    assert [i["id"] for i in result["results"]] == ["lex"]
