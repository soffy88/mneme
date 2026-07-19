"""book_page_plan —— Book Engine Stage 3（W3 Part B B1）。

给定一章（ChapterSpec），产出该章的块序 shell（BlockSpec 列表：类型+参数），
**不生成任何内容**——内容生成是 B2 的工作（各 block_type 对应生成器读
SearchTextbookKnowledge/既有题库/FSRS）。

组合 ≥2 oprim 形态：(1) 静态模板层——按 content_type 查表，确定性、永远可用；
(2) LLM 层——尝试用 LLM 按章节具体内容微调块序/参数，失败即退回静态层。
两层都是本元素自己的代码路径（不是外部依赖），组合关系满足 oskill 定义。

对照 DeepTutor（github.com/HKUDS/DeepTutor）book/agents/page_planner.py 的
SectionArchitect：同样是"LLM 优先、静态模板兜底"两层结构，但 Mneme 的块类型
集合小得多（TEXT/CALLOUT/QUIZ/FIGURE/FLASH_CARDS/GUIDED，无
interactive/animation/timeline——那些 DeepTutor 类型在 Mneme 语境下没有对应
内容源，W3 不做）。

FC-6：带 Mneme 教学假设（GUIDED 块直接对应门控 next_objective 概念），留
mneme-core 私有。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mneme_core.oprim.models import (
    BlockSpec,
    BookBlockType,
    BookContentType,
    ChapterSpec,
)
from mneme_core.oskill.book_ideation import LLMCaller

logger = logging.getLogger(__name__)


# ── 静态模板层（永远可用，确定性） ───────────────────────────────────────────

_STATIC_TEMPLATES: dict[BookContentType, list[tuple[BookBlockType, dict[str, Any]]]] = {
    BookContentType.THEORY: [
        (BookBlockType.TEXT, {"role": "introduction"}),
        (BookBlockType.FIGURE, {"role": "diagram"}),
        (BookBlockType.TEXT, {"role": "deep_dive"}),
        (BookBlockType.CALLOUT, {"variant": "key_idea"}),
        (BookBlockType.QUIZ, {"num_questions": 3}),
        (BookBlockType.FLASH_CARDS, {"count": 5}),
        (BookBlockType.GUIDED, {}),
    ],
    BookContentType.PRACTICE: [
        (BookBlockType.TEXT, {"role": "brief"}),
        (BookBlockType.QUIZ, {"num_questions": 3, "difficulty": "easy"}),
        (BookBlockType.TEXT, {"role": "walkthrough"}),
        (BookBlockType.QUIZ, {"num_questions": 3, "difficulty": "hard"}),
        (BookBlockType.CALLOUT, {"variant": "common_pitfall"}),
    ],
    BookContentType.CONCEPT: [
        (BookBlockType.TEXT, {"role": "definition"}),
        (BookBlockType.FIGURE, {"role": "comparison"}),
        (BookBlockType.TEXT, {"role": "examples"}),
        (BookBlockType.FLASH_CARDS, {"count": 5}),
        (BookBlockType.QUIZ, {"num_questions": 3}),
        (BookBlockType.GUIDED, {}),
    ],
}


def _static_plan(chapter: ChapterSpec) -> list[BlockSpec]:
    template = _STATIC_TEMPLATES.get(
        chapter.content_type, _STATIC_TEMPLATES[BookContentType.THEORY]
    )
    return [BlockSpec(type=bt, params=dict(params)) for bt, params in template]


# ── LLM 层（best effort，失败即回退静态层） ──────────────────────────────────

_ALLOWED_LLM_TYPES = {bt.value for bt in BookBlockType}

_SYSTEM_PROMPT = (
    "你是中国中小学数学教材的活书编辑。给定一章的标题/学习目标/内容形态，"
    "设计这一章的内容块序列（只给类型和简短参数，不生成实际内容）。"
    "可用块类型：text（讲解文字）/callout（要点提示）/quiz（练习题）/"
    "figure（图示）/flash_cards（记忆卡）/guided（接门控的下一步学习指引，"
    "通常放章节末尾）。"
    '只能输出严格 JSON：{"blocks":[{"type":"","params":{}}]}。'
    "块数控制在 4-8 个，且至少包含一个 text 块（否则章节没有讲解正文）。"
)


def _build_messages(chapter: ChapterSpec) -> list[dict]:
    objs = "\n".join(f"- {o}" for o in chapter.learning_objectives) or "（无）"
    user = (
        f"章节标题：{chapter.title}\n"
        f"内容形态：{chapter.content_type.value}\n"
        f"学习目标：\n{objs}\n"
        f"摘要：{chapter.summary or '（无）'}\n\n"
        "请输出上述 JSON 格式的块序列。"
    )
    return [{"role": "user", "content": user}]


def _parse(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _coerce_blocks(raw: Any) -> list[BlockSpec]:
    if not isinstance(raw, list):
        return []
    blocks: list[BlockSpec] = []
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        type_str = str(item.get("type") or "").strip().lower()
        if type_str not in _ALLOWED_LLM_TYPES:
            continue
        params = item.get("params")
        params = dict(params) if isinstance(params, dict) else {}
        blocks.append(BlockSpec(type=BookBlockType(type_str), params=params))
    return blocks


async def book_page_plan(
    caller: LLMCaller,
    *,
    chapter: ChapterSpec,
    llm_enabled: bool = True,
) -> list[BlockSpec]:
    """Stage 3：一章 -> 块序 shell 列表。

    llm_enabled=False 或 LLM 调用/解析失败 -> 静态模板兜底（永远成功，
    不抛异常）。静态层保证至少产出一份可用块序，LLM 层只是"更贴合具体章节"
    的加分项，不是唯一路径。
    """
    if not llm_enabled:
        return _static_plan(chapter)

    try:
        result = await caller(
            messages=_build_messages(chapter),
            system=_SYSTEM_PROMPT,
            max_tokens=800,
        )
        payload = _parse(result.get("content", ""))
    except Exception as e:
        logger.warning("book_page_plan LLM 调用失败，回退静态模板: %s", e)
        return _static_plan(chapter)

    blocks = _coerce_blocks(payload.get("blocks"))
    if not blocks or not any(b.type == BookBlockType.TEXT for b in blocks):
        return _static_plan(chapter)

    return blocks


__all__ = ["book_page_plan"]
