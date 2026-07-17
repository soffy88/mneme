"""persona_store — mneme app 侧对 `persona.*` schema 的唯一访问层（C3，W2C）。

`persona.templates` 由 Alembic 迁移 f7a8b9c0d1e2 建，无 ORM 模型，本层用 schema
限定的原生 SQL（对照 gate_store.py 同一风格）。

FC-6 分类筛判定（书面记录）：模板内容（人格文案）带 Mneme 教学假设（面向中国
中小学生、儿童适龄措辞）→ 私有，不进共享 platform/3O 主库。加载/渲染机制
（`list_personas`/`get_persona`/`render_for_prompt`）形状虽通用，本轮**不迁移**
——避免不成熟的共享包变更；对照本仓库既有先例 D3（mneme-core 7 元素当初也
评估过 platform/3O 共享路线，最终判定留私有，见
MNEME-PHASE1-D1D3-DECISIONS-001.md）。若后续多个项目都要用同一套 persona
加载机制，再单独评估拆分。

红线（不可动摇）：persona 只改"怎么讲"，不改"学什么/过没过门"。本模块**不得**
import 任何门控/判分相关模块（mastery_gate/gate_store/grade/verdict_guard/
cognitive_service）——`tests/test_persona_no_gating_coupling.py` 静态断言此边界。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_PERSONA_SLUG = "encouraging-buddy"


async def list_personas(db: AsyncSession) -> list[dict]:
    """列出全部人格模板（不含 body，供选择器用——body 只在 get_persona 按需取）。"""
    rows = (
        (
            await db.execute(
                text(
                    "SELECT slug, name, description FROM persona.templates "
                    "ORDER BY slug"
                )
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def get_persona(db: AsyncSession, slug: str) -> Optional[dict]:
    """取单个人格模板（含 body，供拼进 system prompt 用）。不存在则 None。"""
    row = (
        (
            await db.execute(
                text(
                    "SELECT slug, name, description, body FROM persona.templates "
                    "WHERE slug = :slug"
                ),
                {"slug": slug},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row is not None else None


def render_for_prompt(persona: dict) -> str:
    """把人格模板渲染成拼进 system prompt 的文本块（对照 DeepTutor persona_style 槽位）。

    纯函数、无 IO——只接受已取到的 persona dict，不查库。
    """
    return (
        f"## 当前人格：{persona['name']}\n"
        f"请始终按以下人格的语气和风格与学生对话（只影响怎么说，不改变教学/"
        f"判分逻辑）：\n\n{persona['body']}"
    )
