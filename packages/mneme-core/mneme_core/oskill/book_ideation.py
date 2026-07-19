"""book_ideation —— Book Engine Stage 1（W3 Part B B1）。

给定教材元信息 + 真实课程结构摘要（knowledge_clusters/knowledge_units，
非 LLM 发明），提议一本活书的框架（标题/描述/范围/预估章数）。

组合 ≥2 oprim 形态：(1) 摘要 prompt 构建（把真实 cluster 数据组织成 LLM
可读的材料）；(2) 注入的 LLM 调用；(3) 容错 JSON 解析 + 校验/兜底
（LLM 输出缺字段或整段解析失败时，退化为一个基于真实数据直接拼出的最小提议，
不让流水线在这一步就崩）。

FC-6：带 Mneme 教材/课程假设（cluster/KU 概念），不进共享 3O 主库，留
mneme-core 私有。

对照 DeepTutor（github.com/HKUDS/DeepTutor）book/agents/ideation_agent.py：
DeepTutor 面对开放域 chat/notebook 输入，本元素面对单本已索引教材 + 真实
cluster 清单——输入更扎实，LLM 不需要"猜这本书该讲什么"，只需要组织/命名。
"""

from __future__ import annotations

import json
from typing import Optional, Protocol

from mneme_core.oprim.models import BookProposal, ClusterSummary, TextbookMeta


class LLMCaller(Protocol):
    """注入式异步 LLM 调用契约，返回 {"content": <原始补全文本>}。

    真 provider（qwen/Ollama）绑定在服务层完成（同 services/textbook_qa_service.py
    的 _get_caller() 模式），本元素不感知具体 provider。
    """

    async def __call__(
        self,
        *,
        messages: list[dict],
        system: Optional[str] = None,
        max_tokens: int = 800,
    ) -> dict: ...


_SYSTEM_PROMPT = (
    "你是中国中小学数学教材的活书编辑。给定一本教材的真实课程结构摘要"
    "（章节聚类+知识点样例，来自已验证的教材索引数据，不是你要发明的内容），"
    "提议一本面向学生自主学习的活书框架。"
    "只能输出严格 JSON："
    '{"title":"","description":"","scope":"","target_level":"","'
    'estimated_chapters":0,"rationale":""}。'
    "estimated_chapters 应参考给出的聚类数量给出一个合理的整合后章数"
    "（通常远少于原始聚类数，因为原始聚类可能重复/过细，需要你合并），"
    "不要凭空编造教材没有的内容。"
)


def _render_clusters(clusters: list[ClusterSummary]) -> str:
    lines = []
    for c in clusters:
        sample = "、".join(c.ku_names_sample) or "（无知识点样例）"
        lines.append(
            f"- [{c.display_order}] {c.name}（{c.ku_count} 个知识点：{sample}）"
        )
    return "\n".join(lines)


def _build_messages(meta: TextbookMeta, clusters: list[ClusterSummary]) -> list[dict]:
    user = (
        f"教材：{meta.book_name}（{meta.subject} · {meta.grade}）\n\n"
        f"真实课程结构（共 {len(clusters)} 个聚类，注意其中可能有重复/相近的聚类，"
        f"提议时应合并同类项）：\n{_render_clusters(clusters)}\n\n"
        "请输出上述 JSON 格式的活书框架提议。"
    )
    return [{"role": "user", "content": user}]


def _parse(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _fallback_proposal(
    meta: TextbookMeta, clusters: list[ClusterSummary]
) -> BookProposal:
    """LLM 解析失败时的兜底：直接基于真实数据拼一个最小提议，不让流水线崩。"""
    estimated = max(1, min(12, len(clusters) // 3)) if clusters else 1
    return BookProposal(
        textbook_id=meta.textbook_id,
        title=f"{meta.book_name}·活书",
        description=f"{meta.book_name}的自主学习活书，覆盖 {len(clusters)} 个课程聚类。",
        scope=meta.book_name,
        target_level=meta.grade,
        estimated_chapters=estimated,
        rationale="LLM 提议解析失败，按真实聚类数量兜底生成。",
    )


async def book_ideation(
    caller: LLMCaller,
    *,
    meta: TextbookMeta,
    clusters: list[ClusterSummary],
) -> BookProposal:
    """Stage 1：教材元信息 + 真实课程结构 -> BookProposal。

    LLM 调用失败（异常/空响应/解析失败）一律走 _fallback_proposal，不抛异常——
    呈现层生成失败不该让整条流水线中断（同 embed_chunks 系列的"失败降级"红线）。
    """
    try:
        result = await caller(
            messages=_build_messages(meta, clusters),
            system=_SYSTEM_PROMPT,
            max_tokens=600,
        )
        payload = _parse(result.get("content", ""))
    except Exception:
        payload = {}

    if not payload or not str(payload.get("title", "")).strip():
        return _fallback_proposal(meta, clusters)

    chapters_raw = payload.get("estimated_chapters", 0)
    try:
        estimated = max(1, min(20, int(chapters_raw)))
    except (TypeError, ValueError):
        estimated = max(1, min(12, len(clusters) // 3)) if clusters else 1

    return BookProposal(
        textbook_id=meta.textbook_id,
        title=str(payload.get("title") or f"{meta.book_name}·活书").strip()[:120],
        description=str(payload.get("description") or "").strip(),
        scope=str(payload.get("scope") or meta.book_name).strip(),
        target_level=str(payload.get("target_level") or meta.grade).strip(),
        estimated_chapters=estimated,
        rationale=str(payload.get("rationale") or "").strip(),
    )


__all__ = ["LLMCaller", "book_ideation"]
