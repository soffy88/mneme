"""book_block_generators —— Book Engine 内容块生成器注册表（W3 Part B B2）。

FC-6：DB 访问 + Mneme 具体 schema（chapter.cluster_ids/knowledge_units 等），
落 services/（同 knowledge_hub_search.py 判定理由），不进 mneme-core（mneme-core
零依赖纯库，碰不了 DB）。

架构关键决定（B2 设计阶段确认，非事后合理化）：
  QUIZ/FLASH_CARDS/GUIDED 三种块本质是"per-student 实时数据"——
    - tool_request_question 需要 student_id（题库按学生状态选题/记录 pending）
    - FSRS 到期队列（get_due_variants）按学生 KCMastery 算
    - next_objective 需要完整 LearningProgress（BKT/FSRS/pending 全量，逐学生现组）
  Book Engine 编译的是**一本教材共享一份**的活书，不是逐学生。所以这三种块
  在编译期只产出"这块覆盖哪些 KC"（kc_ids scope），不产出具体题目/卡片/
  下一步——那些必须在学生真正打开这一页时，调用既有 RequestQuestion/
  SubmitAnswer/FSRS 队列/next_objective 现取，不能在编译期固化。
  这不是偷懒简化，是"确定性判分路由不变"红线的直接推论：提前固化
  等于给每个学生看同一道题/同一张卡，绕开了既有按学生状态选题的逻辑。

  TEXT/CALLOUT/FIGURE 三种块才是真正"编译期生成、所有学生共享"的内容，
  这三种块引用教材原文时必须过 Part B spec §1 的 R1-R4：
    R1: knowledge_hub_search 的 min_score=0.60 直接在查询层过滤
    R3: 每条引用带 citation_state()="inferred_unverified"（默认）
    R4: verified=true 的挂接 -> citation_state()="verified"
    三态在 payload["citations"] 里逐条可见，不是压缩成一个笼统"已核对"标签。

红线：本模块不得 import 门控/判分模块（mastery_gate/gate_store/math_grade/
verdict_guard/cognitive_service）——引用教材是呈现层，QUIZ/FLASH_CARDS/GUIDED
只存 kc_ids，不在这里调 tool_request_question/next_objective 本身（那是渲染期
另一个模块的职责，可能是服务层的另一支路由，不在 B2 范围）。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Protocol

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from mneme_core.oprim.models import BlockSpec, BookBlockType, ChapterSpec
from services.knowledge_hub_search import citation_state, search_knowledge_base

logger = logging.getLogger(__name__)

R1_MIN_SCORE = 0.60  # Part B spec §1 R1——垃圾兜底，非质量门
_MAX_CITED_KUS_PER_BLOCK = 5  # 每块最多带几个 KU 的引用素材，避免 prompt 过长


class LLMCaller(Protocol):
    async def __call__(
        self,
        *,
        messages: list[dict],
        system: Optional[str] = None,
        max_tokens: int = 800,
    ) -> dict: ...


class BlockContext:
    """生成一个块需要的一切（编译期上下文，不含 student_id——见模块顶部说明）。"""

    def __init__(
        self,
        *,
        db: AsyncSession,
        caller: LLMCaller,
        book_id: str,
        chapter: ChapterSpec,
        block: BlockSpec,
    ) -> None:
        self.db = db
        self.caller = caller
        self.book_id = book_id
        self.chapter = chapter
        self.block = block


async def _chapter_ku_ids(db: AsyncSession, chapter: ChapterSpec) -> list[str]:
    """章节 cluster_ids -> 真实 KU id 列表（按 knowledge_units 表，非发明）。"""
    if not chapter.cluster_ids:
        return []
    rows = (
        await db.execute(
            sa_text("SELECT id FROM knowledge_units WHERE cluster_id = ANY(:cids)"),
            {"cids": chapter.cluster_ids},
        )
    ).fetchall()
    return [r[0] for r in rows]


async def _gather_citations(db: AsyncSession, ku_ids: list[str]) -> list[dict]:
    """对章节内若干 KU 各查一次 Knowledge Hub（R1 已在查询层过滤），去重合并。

    只取前 _MAX_CITED_KUS_PER_BLOCK 个 KU 做检索，不是穷举整章——一个块的
    引用素材不需要覆盖章节里每一个 KU，只需要"有真实、过阈值的素材可写"。
    """
    seen_chunk_ids: set[str] = set()
    citations: list[dict] = []
    for ku_id in ku_ids[:_MAX_CITED_KUS_PER_BLOCK]:
        result = await search_knowledge_base(
            db, kc_id=ku_id, top_k=2, min_score=R1_MIN_SCORE
        )
        for r in result["results"]:
            if r["chunk_id"] in seen_chunk_ids:
                continue
            seen_chunk_ids.add(r["chunk_id"])
            citations.append({**r, "citation_state": citation_state(r), "ku_id": ku_id})
    return citations


def _render_citations_for_prompt(citations: list[dict]) -> str:
    if not citations:
        return "（无可用教材原文片段，仅可依据章节标题/学习目标撰写，不得编造具体教材内容）"
    lines = []
    for c in citations:
        excerpt = c["content"].replace("\n", " ")[:200]
        lines.append(f"- [p.{c['page_number']}] {excerpt}")
    return "\n".join(lines)


# ── TEXT ─────────────────────────────────────────────────────────────────────


async def generate_text(ctx: BlockContext) -> dict:
    ku_ids = await _chapter_ku_ids(ctx.db, ctx.chapter)
    citations = await _gather_citations(ctx.db, ku_ids)
    role = ctx.block.params.get("role", "introduction")

    objs = "\n".join(f"- {o}" for o in ctx.chapter.learning_objectives) or "（无）"
    system = (
        "你是中国中小学数学教材的活书撰写者。只依据下面提供的教材原文片段撰写讲解，"
        "不得编造片段之外的具体教材内容（可以用一般性数学常识组织语言，但涉及具体"
        "例子/数据/结论必须来自片段）。若没有可用片段，只能依据章节标题和学习目标"
        "写概括性引导，不得虚构具体例子。控制在 300 字以内。"
    )
    user = (
        f"章节：{ctx.chapter.title}\n"
        f"本段角色：{role}\n"
        f"学习目标：\n{objs}\n\n"
        f"教材原文片段：\n{_render_citations_for_prompt(citations)}\n\n"
        "请撰写这一段讲解文字。"
    )

    try:
        result = await ctx.caller(
            messages=[{"role": "user", "content": user}], system=system, max_tokens=600
        )
        text = (result.get("content") or "").strip()
    except Exception as e:
        logger.warning("generate_text LLM 调用失败: %s", e)
        text = ""

    if not text:
        text = f"本节讲解「{ctx.chapter.title}」。{ctx.chapter.summary}".strip()

    return {"text": text, "role": role, "citations": citations}


# ── CALLOUT ──────────────────────────────────────────────────────────────────


async def generate_callout(ctx: BlockContext) -> dict:
    ku_ids = await _chapter_ku_ids(ctx.db, ctx.chapter)
    citations = await _gather_citations(ctx.db, ku_ids)
    variant = ctx.block.params.get("variant", "key_idea")

    system = (
        "你是中国中小学数学教材的活书撰写者。写一条简短的要点提示（callout），"
        "只依据提供的教材原文片段，不编造片段之外的具体内容。不超过 60 字。"
    )
    user = (
        f"章节：{ctx.chapter.title}\n提示类型：{variant}\n\n"
        f"教材原文片段：\n{_render_citations_for_prompt(citations)}\n\n请撰写这条提示。"
    )

    try:
        result = await ctx.caller(
            messages=[{"role": "user", "content": user}], system=system, max_tokens=150
        )
        text = (result.get("content") or "").strip()
    except Exception as e:
        logger.warning("generate_callout LLM 调用失败: %s", e)
        text = ""

    if not text:
        text = f"注意「{ctx.chapter.title}」中的关键概念。"

    return {"text": text, "variant": variant, "citations": citations}


# ── FIGURE（公式，KaTeX，AA.3 已有前端渲染） ─────────────────────────────────


async def generate_figure(ctx: BlockContext) -> dict:
    """产出一段 LaTeX 公式（$...$/$$...$$），前端 MathText 组件渲染（AA.3），
    不是图片/示意图——本仓库没有图示生成能力，"figure" 块实际内容形态是公式。
    """
    ku_ids = await _chapter_ku_ids(ctx.db, ctx.chapter)
    citations = await _gather_citations(ctx.db, ku_ids)

    system = (
        "你是中国中小学数学教材的活书撰写者。只依据提供的教材原文片段，找出/整理"
        "一个能代表本章内容的数学公式，输出 LaTeX（用 $...$ 包裹行内公式或 $$...$$"
        "包裹独立公式），并给一句简短说明。不得编造片段之外的公式。"
        '只能输出严格 JSON：{"latex":"","caption":""}。'
    )
    user = f"章节：{ctx.chapter.title}\n\n教材原文片段：\n{_render_citations_for_prompt(citations)}"

    import json

    latex, caption = "", ""
    try:
        result = await ctx.caller(
            messages=[{"role": "user", "content": user}], system=system, max_tokens=300
        )
        payload = json.loads(result.get("content") or "{}")
        if isinstance(payload, dict):
            latex = str(payload.get("latex") or "").strip()
            caption = str(payload.get("caption") or "").strip()
    except Exception as e:
        logger.warning("generate_figure LLM 调用/解析失败: %s", e)

    return {"latex": latex, "caption": caption, "citations": citations}


# ── QUIZ / FLASH_CARDS / GUIDED —— 只存 kc_ids scope，不产出具体题目/卡片 ───


async def generate_quiz(ctx: BlockContext) -> dict:
    """只产出这个 quiz 块覆盖哪些 KC——具体题目由学生打开时经既有
    RequestQuestion/SubmitAnswer 现取现判（确定性判分路由不变）。
    """
    ku_ids = await _chapter_ku_ids(ctx.db, ctx.chapter)
    num = max(1, min(8, int(ctx.block.params.get("num_questions", 3))))
    return {
        "kc_ids": ku_ids[:num],
        "difficulty": ctx.block.params.get("difficulty", "medium"),
    }


async def generate_flash_cards(ctx: BlockContext) -> dict:
    """卡片正反面用 KU 自身 name/description（已有课程数据，非 LLM 编造，非
    教材原文引用，不走 R1-R4）；到期/复习调度仍是既有 FSRS 队列的事，这里
    只是"本章有哪些概念可以做记忆卡"的静态清单。
    """
    ku_ids = await _chapter_ku_ids(ctx.db, ctx.chapter)
    count = max(1, min(20, int(ctx.block.params.get("count", 5))))
    selected = ku_ids[:count]

    if not selected:
        return {"kc_ids": [], "cards": []}

    rows = (
        await ctx.db.execute(
            sa_text(
                "SELECT id, name, description FROM knowledge_units WHERE id = ANY(:ids)"
            ),
            {"ids": selected},
        )
    ).fetchall()
    cards = [
        {"ku_id": r.id, "front": r.name, "back": r.description or ""} for r in rows
    ]
    return {"kc_ids": selected, "cards": cards}


async def generate_guided(ctx: BlockContext) -> dict:
    """只存章节 kc_ids scope；真正的 next_objective 调用需要完整
    per-student LearningProgress，必须在渲染期由学生会话触发，不在编译期。
    """
    ku_ids = await _chapter_ku_ids(ctx.db, ctx.chapter)
    return {"kc_ids": ku_ids, "mode": "live_next_objective"}


# ── 注册表 ───────────────────────────────────────────────────────────────────

BLOCK_GENERATORS: dict[BookBlockType, Callable[[BlockContext], Any]] = {
    BookBlockType.TEXT: generate_text,
    BookBlockType.CALLOUT: generate_callout,
    BookBlockType.FIGURE: generate_figure,
    BookBlockType.QUIZ: generate_quiz,
    BookBlockType.FLASH_CARDS: generate_flash_cards,
    BookBlockType.GUIDED: generate_guided,
}


async def generate_block(ctx: BlockContext) -> dict:
    """按 ctx.block.type 分发到对应生成器。失败不 raise——返回
    {"status": "error", "error": ...}，让调用方（B3 book_compile）决定重试/
    跳过策略，不让单个块生成失败拖垮整本书编译。
    """
    generator = BLOCK_GENERATORS.get(ctx.block.type)
    if generator is None:
        return {
            "status": "error",
            "error": f"no generator for block type {ctx.block.type}",
        }
    try:
        payload = await generator(ctx)
    except Exception as e:
        logger.exception("generate_block failed for type=%s: %s", ctx.block.type, e)
        return {"status": "error", "error": str(e)}
    return {"status": "ready", "type": ctx.block.type.value, "payload": payload}


__all__ = ["BlockContext", "LLMCaller", "BLOCK_GENERATORS", "generate_block"]
