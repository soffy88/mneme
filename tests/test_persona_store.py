"""persona_store —— C3（W2C）教学人格模板：list/get/render，纯读，无需写库。

对真实已装 persona.templates（migration f7a8b9c0d1e2）断言。
"""

from __future__ import annotations

import pytest

from obase.db import SessionLocal
from services import persona_store
from services.mcp_router import tool_get_persona, tool_list_personas


@pytest.mark.asyncio
async def test_list_personas_returns_seeded_templates_without_body():
    async with SessionLocal() as db:
        personas = await persona_store.list_personas(db)
        slugs = {p["slug"] for p in personas}
        assert {"encouraging-buddy", "brisk-coach", "curious-explorer"}.issubset(slugs)
        assert all("body" not in p for p in personas)


@pytest.mark.asyncio
async def test_get_persona_returns_full_body():
    async with SessionLocal() as db:
        persona = await persona_store.get_persona(db, "brisk-coach")
        assert persona is not None
        assert persona["name"] == "干脆型教练"
        assert len(persona["body"]) > 0


@pytest.mark.asyncio
async def test_get_persona_unknown_slug_returns_none():
    async with SessionLocal() as db:
        assert await persona_store.get_persona(db, "no-such-persona") is None


def test_render_for_prompt_includes_name_and_body():
    persona = {
        "slug": "x",
        "name": "测试人格",
        "description": "d",
        "body": "独特语气标记XYZ",
    }
    block = persona_store.render_for_prompt(persona)
    assert "测试人格" in block
    assert "独特语气标记XYZ" in block


@pytest.mark.asyncio
async def test_tool_get_persona_falls_back_to_default_on_unknown_slug():
    async with SessionLocal() as db:
        result = await tool_get_persona(db, "no-such-persona")
        assert result["slug"] == persona_store.DEFAULT_PERSONA_SLUG
        assert "prompt_block" in result


@pytest.mark.asyncio
async def test_tool_get_persona_switching_changes_prompt_block():
    """C3-1 验收核心：切换 persona → prompt_block 内容随之变化。"""
    async with SessionLocal() as db:
        a = await tool_get_persona(db, "encouraging-buddy")
        b = await tool_get_persona(db, "brisk-coach")
        assert a["prompt_block"] != b["prompt_block"]
        assert a["name"] != b["name"]


@pytest.mark.asyncio
async def test_tool_list_personas_matches_store():
    async with SessionLocal() as db:
        result = await tool_list_personas(db)
        assert len(result["personas"]) >= 3
