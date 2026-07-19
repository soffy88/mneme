"""tutor_loop.build_tools —— W3 A4 MCP wiring：SearchTextbookKnowledge 真实挂载。

真 HTTP 往返到 mneme-api-1 的 /mcp/SearchTextbookKnowledge（Mneme 自建 Knowledge
Hub，与 SearchKnowledgeBase 的 Stratum 版并存、不同名——见
services/knowledge_hub_search.py 顶部命名冲突说明）。需从仓库根跑，不要 `cd`
进子目录（同 test_tutor_loop_rag_tool.py 排障记录）。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text as sa_text

from obase.auth import create_access_token
from obase.db import SessionLocal
from services.models import User, UserRole

from mneme_agent.assembly.tutor_loop import build_tools

API_BASE = "http://localhost:8000"


def _tool(tools, name):
    return next(t for t in tools if t.name == name)


async def _mk(sid):
    async with SessionLocal() as db:
        db.add(User(id=sid, phone=f"t{sid.hex[:10]}", role=UserRole.student))
        await db.commit()


async def _rm(sid):
    async with SessionLocal() as db:
        await db.execute(
            sa_text("UPDATE users SET deleted_at=now()-interval '1 day' WHERE id=:i"),
            {"i": str(sid)},
        )
        await db.commit()
    async with SessionLocal() as db:
        from services.purge_service import purge_deleted_users

        await purge_deleted_users(db, grace_days=0)
        await db.commit()


def test_build_tools_includes_search_textbook_knowledge():
    tools = build_tools(
        API_BASE, student_id=str(uuid.uuid4()), kc_ids=[], auth_token=None
    )
    names = {t.name for t in tools}
    assert "SearchTextbookKnowledge" in names
    # 两个检索工具必须共存、不互相遮蔽（不同名）
    assert "SearchKnowledgeBase" in names

    tool = _tool(tools, "SearchTextbookKnowledge")
    assert tool.readonly is True


@pytest.mark.asyncio
async def test_search_textbook_knowledge_round_trip_by_kc_id_over_real_http():
    sid = uuid.uuid4()
    await _mk(sid)
    try:
        token = create_access_token({"sub": str(sid)})
        tools = build_tools(API_BASE, student_id=str(sid), kc_ids=[], auth_token=token)
        search = _tool(tools, "SearchTextbookKnowledge").callable

        async with SessionLocal() as db:
            row = (
                await db.execute(sa_text("SELECT ku_id FROM ku_chunk_matches LIMIT 1"))
            ).fetchone()
        assert row is not None, "ku_chunk_matches 为空——先跑 A3 批量挂接"

        result = await search({"kc_id": row[0], "top_k": 3})

        assert "results" in result
        assert isinstance(result["results"], list)
        assert len(result["results"]) == 3
        for r in result["results"]:
            assert r["provenance"] == "inferred"
    finally:
        await _rm(sid)
