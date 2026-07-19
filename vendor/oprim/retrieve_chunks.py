"""oprim.retrieve_chunks — 向量相似度检索（cosine，numpy，无需 pgvector）。

从 textbook_chunks 表检索与 query 最相似的 top-k 块，返回带定位信息的结果。
同时支持关键字兜底（当 embedding 不可用时）。

Version: oprim v1.0.0
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """检索结果：文本块 + 定位 + 相似度分数。"""

    chunk_id: str
    file_id: str
    chunk_index: int
    content: str
    score: float  # cosine 相似度 [0, 1]
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None

    @property
    def citation(self) -> str:
        """人类可读引用字符串，如 「p.23 · 函数的极限」。"""
        parts = []
        if self.page_number:
            parts.append(f"p.{self.page_number}")
        if self.section_title:
            parts.append(self.section_title[:30])
        return " · ".join(parts) if parts else f"段落 {self.chunk_index + 1}"


def _cosine(a: list[float], b: list[float]) -> float:
    """精确 cosine 相似度，numpy 实现。"""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    na = np.linalg.norm(va)
    nb = np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _keyword_score(content: str, query: str) -> float:
    """关键字命中率（兜底，当 embedding 不可用时）。"""
    q_tokens = set(query.lower().split())
    c_lower = content.lower()
    hits = sum(1 for t in q_tokens if t in c_lower)
    return hits / max(len(q_tokens), 1)


async def retrieve_chunks(
    db,  # AsyncSession
    *,
    file_id: str,
    query: str,
    top_k: int = 5,
    min_score: float = 0.3,  # cosine 低于此值过滤
    kc_ids: Optional[list[str]] = None,
) -> list[RetrievedChunk]:
    """
    向量检索：
    1. embed query
    2. 从 DB 加载 file_id 的所有 chunks（含 embedding）
    3. cosine 排序取 top_k
    4. 若无 embedding 可用，退化为关键字匹配

    Parameters
    ----------
    db : AsyncSession
    file_id : str     目标文件 ID
    query : str       用户提问
    top_k : int       最多返回几条
    min_score : float 最低相似度阈值
    """
    from sqlalchemy import text as sa_text
    from oprim.embed_chunks import embed_text

    # ── 1. embed query ────────────────────────────────────────────────────────
    query_vec: Optional[list[float]] = await embed_text(query)

    # ── 2. 加载 chunks ─────────────────────────────────────────────────────────
    rows = (
        await db.execute(
            sa_text("""
        SELECT id, chunk_index, content, page_number, section_title,
               char_start, char_end, embedding
        FROM textbook_chunks
        WHERE file_id = :fid
        ORDER BY chunk_index
    """),
            {"fid": file_id},
        )
    ).fetchall()

    if not rows:
        logger.info("retrieve_chunks: no chunks for file_id=%s", file_id)
        return []

    # ── 3. 打分 ───────────────────────────────────────────────────────────────
    results: list[RetrievedChunk] = []
    use_vec = query_vec is not None

    for row in rows:
        cid, cidx, content, page_num, section, char_start, char_end, embedding = row

        if use_vec and embedding:
            score = _cosine(query_vec, embedding)  # type: ignore[arg-type]
        else:
            # 降级：关键字兜底
            score = _keyword_score(content, query)

        if score < min_score:
            continue

        results.append(
            RetrievedChunk(
                chunk_id=cid,
                file_id=file_id,
                chunk_index=cidx,
                content=content,
                score=score,
                page_number=page_num,
                section_title=section,
                char_start=char_start,
                char_end=char_end,
            )
        )

    # ── 4. 排序取 top_k ───────────────────────────────────────────────────────
    results.sort(key=lambda r: r.score, reverse=True)
    top_results = results[:top_k]

    # ── 5. LightRAG (Graph) 补全 ───────────────────────────────────────────────
    # 如果传了 kc_ids，顺带把知识图谱里的前置/关联关系作为额外的上下文块打包送出
    if kc_ids:
        from services.models import KnowledgeUnit
        from sqlalchemy import select

        kus = (
            (
                await db.execute(
                    select(KnowledgeUnit).where(KnowledgeUnit.id.in_(kc_ids))
                )
            )
            .scalars()
            .all()
        )
        for ku in kus:
            graph_content = f"知识点【{ku.name}】属于图谱中的一环。它的"
            if ku.prerequisites:
                graph_content += f"硬前置知识点有: {', '.join(ku.prerequisites)}；"
            if ku.soft_prerequisites:
                graph_content += f"软前置知识点有: {', '.join(ku.soft_prerequisites)}；"
            if ku.related_kus:
                graph_content += f"相关知识点有: {', '.join(ku.related_kus)}。"

            if "前置" in graph_content or "相关" in graph_content:
                top_results.append(
                    RetrievedChunk(
                        chunk_id=f"graph-{ku.id}",
                        file_id=file_id,
                        chunk_index=-1,
                        content=graph_content,
                        score=1.0,  # 图谱结构知识作为最高优
                        page_number=None,
                        section_title="知识图谱",
                    )
                )

    return top_results


def format_chunks_as_context(
    chunks: list[RetrievedChunk], max_chars: int = 2000
) -> str:
    """
    将检索结果格式化为 LLM prompt 的 <context> 段，带引用标记。

    输出格式：
        [p.23 · 等差数列] 等差数列是指...
        [p.45 · 求和公式] 等差数列前n项和...
    """
    lines: list[str] = []
    total = 0
    for chunk in chunks:
        cite = chunk.citation
        snippet = chunk.content[:500]  # 每块最多500字避免撑爆 context
        line = f"[{cite}] {snippet}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)
    return "\n\n".join(lines)
