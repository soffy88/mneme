"""knowledge_hub_search —— Mneme 自建 Knowledge Hub 检索（W3 A4，非 C4 的 Stratum 版）。

FC-6 分类筛判定（书面记录）：本模块直接查询 Mneme 自己的
`textbook_chunks`/`ku_chunk_matches`/`textbook_files`/`textbooks` 表，返回结构
绑定这套 Mneme 专属 schema（chunk_id/pdf_id/char_span/textbook_meta 等字段），
不是通用检索抽象——同 `services/rag_client.py`（Stratum 客户端）的判定理由，
落 `services/`（Mneme 本地，Layer4），不进共享 oprim/oskill。

红线：Knowledge Hub 检索只作呈现层素材，**不进门控判据**——本模块不得 import
任何门控/判分模块（mastery_gate/gate_store/math_grade/verdict_guard/
cognitive_service）。`tests/test_knowledge_hub_search_no_gating_coupling.py`
静态断言此边界（对照 C3 persona / C5 memory / C4 rag 同一模式）。

A3 教训（吸收进设计，不是事后声明）：
  - 挂接是概率匹配，A3 抽验 20 个 KU 命中率 ~85%（1/20 明确误判：小数点移动
    被匹配到几何图形缩放，因为两者共享"放大/缩小"的表面词汇）。本模块因此：
    1. 永远返回全部候选（默认 top_k=3），不只第一名——不让调用方误以为
       rank-1 就是唯一/权威答案。
    2. 每条结果都带 `score`（cosine 相似度原始值，不做归一化美化），调用方
       可自行设阈值过滤，本模块不代为决定"够不够可信"。
    3. 每条结果 `provenance` 字段硬编码为 `"inferred"`——不伪装成权威出处。
  - 命名刻意避开与 C4 Stratum 工具同名的 "SearchKnowledgeBase"：两者若同名，
    MCP 工具列表/路由表都不会报错，而是静默让后注册的一个被永久遮蔽（第二个
    路由/工具形同虚设，调用永远落到先注册的那个）——实测确认，不是猜测。
    故本模块对外暴露为 "SearchTextbookKnowledge"，与 Stratum 版共存
    （spec 全局不变式：C4 Stratum RAG 留作可选，Book/Hub 零依赖）。

Version: services v1.0.0（W3 A4）
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    na = np.linalg.norm(va)
    nb = np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _row_to_result(
    *,
    chunk_id: str,
    pdf_id: str,
    page_number: Optional[int],
    char_start: Optional[int],
    char_end: Optional[int],
    content: str,
    subject: Optional[str],
    grade: Optional[str],
    book_name: Optional[str],
    score: float,
    rank: int,
) -> dict:
    return {
        "chunk_id": chunk_id,
        "pdf_id": pdf_id,
        "page_number": page_number,
        "char_start": char_start,
        "char_end": char_end,
        "content": content,
        "textbook_meta": {"subject": subject, "grade": grade, "book_name": book_name},
        "score": round(score, 4),
        "rank": rank,
        # 硬编码，不是从数据推导——防止未来有人"优化"成看分数动态判断权威性。
        "provenance": "inferred",
    }


async def _search_by_kc_id(db: AsyncSession, kc_id: str, top_k: int) -> list[dict]:
    """走 A3 预计算的 ku_chunk_matches（无需实时 embed，确定性、快）。"""
    rows = (
        await db.execute(
            sa_text("""
        SELECT tc.id, tc.file_id, tc.page_number, tc.char_start, tc.char_end,
               tc.content, t.subject, t.grade, t.book_name, kcm.score, kcm.rank
        FROM ku_chunk_matches kcm
        JOIN textbook_chunks tc ON tc.id = kcm.chunk_id
        JOIN textbook_files tf ON tf.id = tc.file_id
        LEFT JOIN textbooks t ON t.id = tf.textbook_id
        WHERE kcm.ku_id = :kc_id
        ORDER BY kcm.rank
        LIMIT :top_k
    """),
            {"kc_id": kc_id, "top_k": top_k},
        )
    ).fetchall()

    return [
        _row_to_result(
            chunk_id=r.id,
            pdf_id=r.file_id,
            page_number=r.page_number,
            char_start=r.char_start,
            char_end=r.char_end,
            content=r.content,
            subject=r.subject,
            grade=r.grade,
            book_name=r.book_name,
            score=r.score,
            rank=r.rank,
        )
        for r in rows
    ]


async def _search_by_free_text(db: AsyncSession, query: str, top_k: int) -> list[dict]:
    """实时 embed query + 语料库全量 numpy cosine（复用 embed_chunks.embed_text，
    与 chunk 入库时同一模型——否则向量空间不一致，相似度没有意义）。
    """
    from oprim.embed_chunks import embed_text

    query_vec = await embed_text(query)
    if query_vec is None:
        logger.warning("search_knowledge_base: embed_text 返回 None，降级为空结果")
        return []

    rows = (
        await db.execute(
            sa_text("""
        SELECT tc.id, tc.file_id, tc.page_number, tc.char_start, tc.char_end,
               tc.content, tc.embedding, t.subject, t.grade, t.book_name
        FROM textbook_chunks tc
        JOIN textbook_files tf ON tf.id = tc.file_id
        LEFT JOIN textbooks t ON t.id = tf.textbook_id
        WHERE tc.embedding IS NOT NULL
    """)
        )
    ).fetchall()

    scored = sorted(
        ((r, _cosine(query_vec, r.embedding)) for r in rows),
        key=lambda x: x[1],
        reverse=True,
    )

    return [
        _row_to_result(
            chunk_id=r.id,
            pdf_id=r.file_id,
            page_number=r.page_number,
            char_start=r.char_start,
            char_end=r.char_end,
            content=r.content,
            subject=r.subject,
            grade=r.grade,
            book_name=r.book_name,
            score=score,
            rank=rank,
        )
        for rank, (r, score) in enumerate(scored[:top_k], 1)
    ]


async def search_knowledge_base(
    db: AsyncSession,
    *,
    kc_id: Optional[str] = None,
    query: Optional[str] = None,
    top_k: int = 3,
) -> dict:
    """Knowledge Hub 检索主入口。

    kc_id 与 query 二选一（不可同时为空，同时给出时 kc_id 优先——复用 A3
    预计算结果，确定性更好、无需实时 embed 调用）。

    返回 {"query_type": "kc_id"|"free_text", "results": [...]}；results 永远是
    列表（找不到内容/embedding 不可用时为空列表，不抛异常——呈现层素材缺失
    不该打断调用方）。
    """
    if not kc_id and not query:
        return {"query_type": None, "results": []}

    if kc_id:
        results = await _search_by_kc_id(db, kc_id, top_k)
        return {"query_type": "kc_id", "results": results}

    assert query is not None
    results = await _search_by_free_text(db, query, top_k)
    return {"query_type": "free_text", "results": results}
