"""RecallMemory / RememberEpisode —— C5（W2C）mneme-agent MCP wiring。

真 DB 写入（agent.* schema）；单 session 不 commit，退出回滚，不污染库。
"""

from __future__ import annotations

import uuid

import pytest

from obase.db import SessionLocal
from services.mcp_router import tool_recall_memory, tool_remember_episode
from services.memory import update


@pytest.mark.asyncio
async def test_tool_remember_episode_writes_and_returns_id():
    async with SessionLocal() as db:
        sid = uuid.uuid4()
        result = await tool_remember_episode(
            db, sid, kind="tutor_turn", content={"note": "学生问了函数的定义"}
        )
        assert result["kind"] == "tutor_turn"
        assert result["id"]


@pytest.mark.asyncio
async def test_tool_recall_memory_by_topic():
    async with SessionLocal() as db:
        sid = uuid.uuid4()
        await update(
            db, sid, topic="algebra", content={"summary": "学生对函数概念较熟悉"}
        )

        result = await tool_recall_memory(db, sid, "algebra")
        assert result["memories"] == [
            {"topic": "algebra", "content": {"summary": "学生对函数概念较熟悉"}}
        ]


@pytest.mark.asyncio
async def test_tool_recall_memory_no_topic_returns_recent():
    async with SessionLocal() as db:
        sid = uuid.uuid4()
        result = await tool_recall_memory(db, sid, None)
        assert result == {"memories": []}
