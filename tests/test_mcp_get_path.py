"""GetPath —— 按学生档案派生学习路径（AA.5）。

对真实已装教材 renjiao-math-g10-a 断言：路径非空、只含"有内容"KC、按章节序（起点是集合
类基础，非高阶应用）。派生式路径无需 seed；跨会话确定性稳定。
"""

from __future__ import annotations

import uuid

import pytest

from obase.db import SessionLocal
from services.mcp_router import (
    DEFAULT_TEXTBOOK,
    _CONTENT_KC_SQL,
    tool_get_path,
)


@pytest.mark.asyncio
async def test_get_path_content_filtered_and_ordered():
    async with SessionLocal() as db:
        p = await tool_get_path(db, uuid.uuid4())
        assert p["textbook_id"] == DEFAULT_TEXTBOOK
        kc = p["kc_ids"]
        assert len(kc) > 0, "路径不应为空（g10-a 已装内容）"

        # 只含"有内容"的 KC（题库自足题 或 rubric）—— 不会撞到无内容/占位题
        content = {r[0] for r in (await db.execute(_CONTENT_KC_SQL)).all() if r[0]}
        assert set(kc).issubset(content)

        # 章节序：起点是集合类基础（display_order 最前），不是高阶应用
        assert ("集合" in kc[0]) or ("数集" in kc[0]), (
            f"起点应为集合类基础，实得 {kc[0]}"
        )

        # 无重复
        assert len(kc) == len(set(kc))
