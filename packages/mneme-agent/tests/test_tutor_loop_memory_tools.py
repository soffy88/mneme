"""tutor_loop.build_tools —— C5 MCP wiring：RecallMemory / RememberEpisode 真实挂载。

真 HTTP 往返（对照 test_mcp_http_acceptance.py 同一惯例，AA.1 起要 JWT，harness 现铸
该学生自己的 token）。需从仓库根跑（`pytest packages/mneme-agent/tests/...`），不要
`cd` 进子目录——否则 `.env` 找不到、JWT_SECRET 静默退化成 dev 默认值（见 TASKS.md C1
排障记录）。
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


def test_build_tools_includes_memory_tools():
    tools = build_tools(
        API_BASE, student_id=str(uuid.uuid4()), kc_ids=[], auth_token=None
    )
    names = {t.name for t in tools}
    assert {"RecallMemory", "RememberEpisode"}.issubset(names)
    assert (
        len(tools) == 12
    )  # 8 既有 + 2（C5）+ 1（C4 SearchKnowledgeBase）+ 1（W3 A4 SearchTextbookKnowledge）

    recall = _tool(tools, "RecallMemory")
    assert recall.readonly is True
    remember = _tool(tools, "RememberEpisode")
    assert remember.readonly is False
    assert set(remember.input_schema["required"]) == {"kind", "content"}


@pytest.mark.asyncio
async def test_remember_then_recall_round_trip_over_real_http():
    sid = uuid.uuid4()
    await _mk(sid)
    try:
        token = create_access_token({"sub": str(sid)})
        tools = build_tools(API_BASE, student_id=str(sid), kc_ids=[], auth_token=token)
        remember = _tool(tools, "RememberEpisode").callable
        recall = _tool(tools, "RecallMemory").callable

        r = await remember(
            {"kind": "tutor_turn", "content": {"note": "讨论了函数的定义"}}
        )
        assert "id" in r

        out = await recall({"topic": None})
        assert out == {
            "memories": []
        }  # RememberEpisode 写 episodic，recall 读 semantic——互不相通
    finally:
        await _rm(sid)
