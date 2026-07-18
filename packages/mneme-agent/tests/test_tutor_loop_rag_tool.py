"""tutor_loop.build_tools —— C4 MCP wiring：SearchKnowledgeBase 真实挂载。

真 HTTP 往返到 mneme-api-1 的 /mcp/SearchKnowledgeBase（该端点再代理转发给 Stratum
——本测试不直接碰 Stratum，只验证 Mneme 这一跳的真实挂载）。需从仓库根跑，不要
`cd` 进子目录（同 test_tutor_loop_memory_tools.py 排障记录）。
"""

from __future__ import annotations

import uuid

import pytest

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
    from sqlalchemy import text

    async with SessionLocal() as db:
        await db.execute(
            text("UPDATE users SET deleted_at=now()-interval '1 day' WHERE id=:i"),
            {"i": str(sid)},
        )
        await db.commit()
    async with SessionLocal() as db:
        from services.purge_service import purge_deleted_users

        await purge_deleted_users(db, grace_days=0)
        await db.commit()


def test_build_tools_includes_search_knowledge_base():
    tools = build_tools(
        API_BASE, student_id=str(uuid.uuid4()), kc_ids=[], auth_token=None
    )
    names = {t.name for t in tools}
    assert "SearchKnowledgeBase" in names

    tool = _tool(tools, "SearchKnowledgeBase")
    assert tool.readonly is True
    assert tool.input_schema["required"] == ["query"]


@pytest.mark.asyncio
async def test_search_knowledge_base_round_trip_over_real_http():
    sid = uuid.uuid4()
    await _mk(sid)  # /mcp/* 鉴权要真实存在的用户（同 test_mcp_http_acceptance.py 惯例）
    try:
        token = create_access_token({"sub": str(sid)})
        tools = build_tools(API_BASE, student_id=str(sid), kc_ids=[], auth_token=token)
        search = _tool(tools, "SearchKnowledgeBase").callable

        result = await search({"query": "函数", "top_k": 3})

        # 不断言非空结果——Stratum 服务账号语料库当前是空的（内容填充是独立后续工作，
        # C4 本身只交付检索通路），但断言"通路真的走通了"：不是 HTTP 错误/异常。
        assert "results" in result
        assert isinstance(result["results"], list)
        assert "error" not in result
    finally:
        await _rm(sid)
