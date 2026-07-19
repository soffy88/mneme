"""book_spine —— Book Engine Stage 2（W3 Part B B1）。

给定 Stage 1 的 BookProposal + 真实课程结构摘要，把（可能重复/过细的）原始
cluster 列表**合并整理**成一棵干净的章节树（ChapterSpec 列表），每章显式
绑定它扎根的真实 cluster_id（出处），不是 DeepTutor 式自由 source_anchors。

prerequisites（章节间前置关系）由 LLM 生成——spec 明确要求"不引外部前置图"
（os-taxonomy 已废，不接那套前置图基础设施）。

组合 ≥2 oprim 形态：(1) prompt 构建；(2) 注入的 LLM 调用；(3) 容错解析 +
校验（章节标题去重、cluster_id 必须真实存在于输入清单里——防止 LLM 编造不
存在的 cluster_id）+ 兜底（解析失败/全部校验不过 -> 每个 cluster 各自成一章，
1:1 兜底，不合并，但保证不崩、不丢内容）。

FC-6：带 Mneme 教材/课程假设，留 mneme-core 私有。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from mneme_core.oprim.models import (
    BookContentType,
    BookProposal,
    BookSpine,
    ChapterSpec,
    ClusterSummary,
)
from mneme_core.oskill.book_ideation import LLMCaller

_SYSTEM_PROMPT = (
    "你是中国中小学数学教材的活书编辑。给定活书框架提议 + 真实课程聚类清单"
    "（可能有重复/过细的聚类，需要你合并同类项），设计一棵干净的章节树。"
    "每章必须显式列出它对应的一个或多个真实聚类 id（cluster_ids）——"
    "只能使用给出清单里真实存在的 cluster_id，不能编造。"
    "只能输出严格 JSON："
    '{"chapters":[{"title":"","content_type":"theory|practice|concept",'
    '"learning_objectives":[],"cluster_ids":[],"prerequisites":[],'
    '"summary":""}]}。'
    "prerequisites 填其他章节的 title（不是 cluster_id），表示学习顺序上的前置章节。"
)


def _render_clusters(clusters: list[ClusterSummary]) -> str:
    lines = []
    for c in clusters:
        sample = "、".join(c.ku_names_sample) or "（无知识点样例）"
        lines.append(f"- id={c.cluster_id} [{c.display_order}] {c.name}（{sample}）")
    return "\n".join(lines)


def _build_messages(
    proposal: BookProposal, clusters: list[ClusterSummary]
) -> list[dict]:
    user = (
        f"活书提议：{proposal.title}\n"
        f"描述：{proposal.description}\n"
        f"范围：{proposal.scope}\n"
        f"预估章数：{proposal.estimated_chapters}\n\n"
        f"真实课程聚类清单（共 {len(clusters)} 个）：\n{_render_clusters(clusters)}\n\n"
        "请输出上述 JSON 格式的章节树。"
    )
    return [{"role": "user", "content": user}]


def _parse(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _coerce_content_type(raw: Any) -> BookContentType:
    try:
        return BookContentType(str(raw or "theory").strip().lower())
    except ValueError:
        return BookContentType.THEORY


def _fallback_spine(
    book_id: str, proposal: BookProposal, clusters: list[ClusterSummary]
) -> BookSpine:
    """LLM 解析失败/全部校验不过时的兜底：每个真实 cluster 各自成一章，
    1:1 直接映射，不合并——保证内容不丢、cluster_id 100% 真实，但没有 LLM
    带来的合并/去重收益。
    """
    chapters = [
        ChapterSpec(
            id=f"ch_{uuid.uuid4().hex[:10]}",
            title=c.name,
            content_type=BookContentType.THEORY,
            cluster_ids=[c.cluster_id],
            summary=f"覆盖 {c.ku_count} 个知识点。",
            order=idx,
        )
        for idx, c in enumerate(clusters)
    ]
    return BookSpine(
        book_id=book_id, textbook_id=proposal.textbook_id, chapters=chapters
    )


def _coerce_chapters(raw: Any, valid_cluster_ids: set[str]) -> list[ChapterSpec]:
    if not isinstance(raw, list):
        return []
    chapters: list[ChapterSpec] = []
    seen_titles: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:160]
        if not title or title.lower() in seen_titles:
            continue

        cluster_ids_raw = item.get("cluster_ids") or []
        if not isinstance(cluster_ids_raw, list):
            cluster_ids_raw = []
        # 只保留输入清单里真实存在的 cluster_id——防止 LLM 编造出处
        cluster_ids = [
            str(cid) for cid in cluster_ids_raw if str(cid) in valid_cluster_ids
        ]
        if not cluster_ids:
            continue  # 没有真实出处的章节，整章丢弃（宁缺毋滥，不留无出处章节）

        seen_titles.add(title.lower())

        objectives_raw = item.get("learning_objectives") or []
        if not isinstance(objectives_raw, list):
            objectives_raw = []
        objectives = [
            str(o).strip()[:200] for o in objectives_raw if str(o or "").strip()
        ][:6]

        prereq_raw = item.get("prerequisites") or []
        if not isinstance(prereq_raw, list):
            prereq_raw = []
        prerequisites = [
            str(p).strip()[:160] for p in prereq_raw if str(p or "").strip()
        ][:4]

        chapters.append(
            ChapterSpec(
                id=f"ch_{uuid.uuid4().hex[:10]}",
                title=title,
                content_type=_coerce_content_type(item.get("content_type")),
                learning_objectives=objectives,
                cluster_ids=cluster_ids,
                prerequisites=prerequisites,
                summary=str(item.get("summary") or "").strip()[:400],
            )
        )
    return chapters


async def book_spine(
    caller: LLMCaller,
    *,
    book_id: str,
    proposal: BookProposal,
    clusters: list[ClusterSummary],
) -> BookSpine:
    """Stage 2：BookProposal + 真实聚类清单 -> BookSpine（章节树）。

    章节的 prerequisites 用 title 表示，调用方（book_page_plan/后续 B3）需要
    自行把 title 解析回 chapter id——这里不做，避免本函数因解析失败而整体失败。
    """
    valid_cluster_ids = {c.cluster_id for c in clusters}

    try:
        result = await caller(
            messages=_build_messages(proposal, clusters),
            system=_SYSTEM_PROMPT,
            max_tokens=2000,
        )
        payload = _parse(result.get("content", ""))
    except Exception:
        payload = {}

    chapters = _coerce_chapters(payload.get("chapters"), valid_cluster_ids)
    if not chapters:
        return _fallback_spine(book_id, proposal, clusters)

    # title -> order 前置关系用章节顺序兜底（LLM 给的 prerequisites 是 title，
    # 这里只保证 order 字段本身单调递增，前置关系的实际解析留给调用方）
    for idx, ch in enumerate(chapters):
        ch.order = idx

    return BookSpine(
        book_id=book_id, textbook_id=proposal.textbook_id, chapters=chapters
    )


__all__ = ["book_spine"]
