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
