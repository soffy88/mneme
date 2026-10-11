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

import asyncio
import logging
import os
import re
import time
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


# Query embedding 熔断：oprim.embed_chunks 的 Ollama 调用超时是 60s——embed 服务
# 宕机时（2026-10-11 实况：GPU 掉卡，Ollama 请求全部挂起）每次聊天检索都要白等
# 一分钟才落到词面兜底。这里给 query embedding 单独加短超时，失败后冷却一段时间
# 直接跳过语义检索，冷却期满再试。
QUERY_EMBED_TIMEOUT_S = float(os.environ.get("KNOWLEDGE_HUB_EMBED_TIMEOUT_S", "10"))
EMBED_COOLDOWN_S = float(os.environ.get("KNOWLEDGE_HUB_EMBED_COOLDOWN_S", "60"))
_EMBED_STATE: dict[str, float] = {"down_until": 0.0}


async def _embed_query(query: str) -> tuple[Optional[list[float]], Optional[str]]:
    """返回 (query 向量, 模型名)；模型名 None = 旧路径（按维度匹配旧列）。

    后端由 MNEME_EMBED_BACKEND 决定（见 services/text_embedder）；超时与熔断
    对两种后端一视同仁。
    """
    from services.text_embedder import embed_query

    now = time.monotonic()
    if _EMBED_STATE["down_until"] > now:
        return None, None
    model: Optional[str] = None
    try:
        vec, model = await asyncio.wait_for(
            embed_query(query, timeout=QUERY_EMBED_TIMEOUT_S),
            timeout=QUERY_EMBED_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "search_knowledge_base: query embedding 超时（>%.0fs）", QUERY_EMBED_TIMEOUT_S
        )
        vec = None
    if vec is None:
        _EMBED_STATE["down_until"] = time.monotonic() + EMBED_COOLDOWN_S
    return vec, model


# ── 相似度阈值：按"打分模型 × 用途"标定 ─────────────────────────────────────
# cosine 的量纲随模型变：旧 qwen3-embedding（4096 维）真相关 ~0.62-0.72、无关
# ~0.44-0.54，于是 Book Engine R1=0.60、tutor 回落素材下限=0.58。CPU 侧车模型的
# 分布不同，必须单独标定（docs/knowledge_hub_cpu_embedding.md 记录标注集与结果）。
#   "book"：Book Engine R1 垃圾兜底（宁缺毋滥）
#   "chat"：tutor SearchKnowledgeBase 回落素材下限
# 可用环境变量覆盖：KNOWLEDGE_HUB_MIN_SCORE_<MODEL>_<PURPOSE>，如
# KNOWLEDGE_HUB_MIN_SCORE_BGE_SMALL_ZH_V1_5_BOOK=0.6。
LEGACY_MODEL_KEY = "legacy"
MIN_SCORE_PROFILES: dict[str, dict[str, float]] = {
    LEGACY_MODEL_KEY: {"book": 0.60, "chat": 0.58},
    "bge-small-zh-v1.5": {"book": 0.60, "chat": 0.58},
}


def min_score_for(purpose: str, model: Optional[str] = None) -> float:
    key = model or LEGACY_MODEL_KEY
    env = f"KNOWLEDGE_HUB_MIN_SCORE_{re.sub(r'[^A-Za-z0-9]', '_', key).upper()}_{purpose.upper()}"
    if os.environ.get(env):
        try:
            return float(os.environ[env])
        except ValueError:
            logger.warning("%s=%r 不是数字，忽略", env, os.environ[env])
    profile = MIN_SCORE_PROFILES.get(key) or MIN_SCORE_PROFILES[LEGACY_MODEL_KEY]
    return profile[purpose]


def _model_of_method(method: Optional[str]) -> Optional[str]:
    """ku_chunk_matches.method → 打分模型 key（旧 A3 行 = None → legacy 档）。"""
    if method:
        for m in MIN_SCORE_PROFILES:
            if m != LEGACY_MODEL_KEY and method.endswith(m):
                return m
    return None


# 进程内向量矩阵缓存：每次查询先跑一条廉价指纹 SQL（行数 + 最近 embed/创建时间），
# 指纹不变就复用已归一化的矩阵，避免每次把全库 4096 维向量从 Postgres 拉一遍
# （2026-10 实测 4.9k chunk 时单次 ~2s，语料扩到多学科后线性变慢）。
# 语义与旧实现一致：同一 cosine、同一 min_score 过滤、同一降序排序。
_EMB_CACHE: dict[tuple[Optional[str], int], tuple[tuple, list[str], np.ndarray]] = {}


def _normalized(ids: list[str], vecs: list, dim: int) -> tuple[list[str], np.ndarray]:
    if ids:
        mat = np.asarray(vecs, dtype=np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0  # 零向量 → 分数 0（同旧 _cosine 行为）
        return ids, mat / norms
    return ids, np.zeros((0, dim), dtype=np.float32)


async def _embedding_matrix(
    db: AsyncSession, dim: int, model: Optional[str] = None
) -> tuple[list[str], np.ndarray]:
    """model=None：旧列 textbook_chunks.embedding（按维度筛）；
    model=名字：textbook_chunk_embeddings 里该模型的向量（CPU 侧车）。"""
    if model is None:
        fp_sql = """
        SELECT count(*) AS n, max(tc.embedded_at) AS e, max(tc.created_at) AS c,
               count(DISTINCT tc.file_id) AS f
        FROM textbook_chunks tc
        JOIN textbook_files tf ON tf.id = tc.file_id
        WHERE tc.embedding IS NOT NULL
    """
        rows_sql = """
        SELECT tc.id, tc.embedding
        FROM textbook_chunks tc
        JOIN textbook_files tf ON tf.id = tc.file_id
        WHERE tc.embedding IS NOT NULL
    """
        params: dict = {}
    else:
        fp_sql = """
        SELECT count(*) AS n, max(e.embedded_at) AS e, max(tc.created_at) AS c,
               count(DISTINCT tc.file_id) AS f
        FROM textbook_chunk_embeddings e
        JOIN textbook_chunks tc ON tc.id = e.chunk_id
        JOIN textbook_files tf ON tf.id = tc.file_id
        WHERE e.model = :model
    """
        rows_sql = """
        SELECT tc.id, e.embedding
        FROM textbook_chunk_embeddings e
        JOIN textbook_chunks tc ON tc.id = e.chunk_id
        JOIN textbook_files tf ON tf.id = tc.file_id
        WHERE e.model = :model
    """
        params = {"model": model}

    fp_row = (await db.execute(sa_text(fp_sql), params)).one()
    fp = (fp_row.n, fp_row.e, fp_row.c, fp_row.f)
    cached = _EMB_CACHE.get((model, dim))
    if cached is not None and cached[0] == fp:
        return cached[1], cached[2]

    rows = (await db.execute(sa_text(rows_sql), params)).fetchall()
    same = [r for r in rows if len(r.embedding) == dim]
    ids, mat = _normalized([r.id for r in same], [r.embedding for r in same], dim)
    _EMB_CACHE[(model, dim)] = (fp, ids, mat)
    return ids, mat


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
    verified: bool = False,
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
        # R4（Part B spec）：ku_chunk_matches.verified 人工确认过才 True；
        # free_text 路径不经 KU 挂接，恒为 False（没有对应的人工校订机制）。
        "verified": verified,
    }


def citation_state(result: dict) -> str:
    """R3/R4 三态标注（Part B spec §1）：verified=True -> "verified"（已核对
    出处），否则 "inferred_unverified"（推断出处·未经人工核对）——分数高低
    不改变这个判断，0.732 也可能是错的，分数不是可信度证明（A3/A4 已定论）。
    """
    return "verified" if result.get("verified") else "inferred_unverified"


async def _search_by_kc_id(
    db: AsyncSession,
    kc_id: str,
    top_k: int,
    min_score: float,
    purpose: Optional[str] = None,
) -> list[dict]:
    """走 A3 预计算的 ku_chunk_matches（无需实时 embed，确定性、快）。

    min_score 在 SQL 里过滤（R1：垃圾兜底，不是质量门——见模块顶部说明），
    rank 仍按数据库里原始 rank 呈现（过滤后可能不连续，如实反映"这是原始
    候选里的第几名"，不重新编号造成"这是完整 top-N"的错觉）。

    purpose 给定时（"book"/"chat"），阈值按每行的打分模型（method）取标定值——
    数学 KU 的旧 A3 行是 qwen3 量纲，2026-10 补挂的物理/语文/历史/英语行是
    CPU 侧车模型（bge-small-zh-v1.5）量纲，同一个数字不能同时套两者。min_score 仍作为额外下限生效。
    """
    if purpose:
        return await _search_by_kc_id_purpose(db, kc_id, top_k, min_score, purpose)
    rows = (
        await db.execute(
            sa_text("""
        SELECT tc.id, tc.file_id, tc.page_number, tc.char_start, tc.char_end,
               tc.content, t.subject, t.grade, t.book_name, kcm.score, kcm.rank,
               kcm.verified
        FROM ku_chunk_matches kcm
        JOIN textbook_chunks tc ON tc.id = kcm.chunk_id
        JOIN textbook_files tf ON tf.id = tc.file_id
        LEFT JOIN textbooks t ON t.id = tf.textbook_id
        WHERE kcm.ku_id = :kc_id AND kcm.score >= :min_score
        ORDER BY kcm.rank
        LIMIT :top_k
    """),
            {"kc_id": kc_id, "top_k": top_k, "min_score": min_score},
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
            verified=bool(r.verified),
        )
        for r in rows
    ]


async def _search_by_kc_id_purpose(
    db: AsyncSession, kc_id: str, top_k: int, min_score: float, purpose: str
) -> list[dict]:
    rows = (
        await db.execute(
            sa_text("""
        SELECT tc.id, tc.file_id, tc.page_number, tc.char_start, tc.char_end,
               tc.content, t.subject, t.grade, t.book_name, kcm.score, kcm.rank,
               kcm.verified, kcm.method
        FROM ku_chunk_matches kcm
        JOIN textbook_chunks tc ON tc.id = kcm.chunk_id
        JOIN textbook_files tf ON tf.id = tc.file_id
        LEFT JOIN textbooks t ON t.id = tf.textbook_id
        WHERE kcm.ku_id = :kc_id
        ORDER BY kcm.rank
    """),
            {"kc_id": kc_id},
        )
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        floor = max(min_score, min_score_for(purpose, _model_of_method(r.method)))
        if r.score < floor:
            continue
        out.append(
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
                verified=bool(r.verified),
            )
        )
        if len(out) >= top_k:
            break
    return out


_LEXICAL_CANDIDATE_LIMIT = 400
_TERM_SPLIT = re.compile(r"[\s,，。.;；:：!！?？、()（）\[\]【】\"'“”‘’《》<>/|]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def _lexical_terms(query: str) -> list[str]:
    """把 query 切成检索词：按空白/标点切分，去重保序，丢掉单字符噪声。"""
    seen: list[str] = []
    for t in _TERM_SPLIT.split(query.strip()):
        t = t.strip()
        if len(t) >= 2 and t not in seen:
            seen.append(t)
    return seen


def _cjk_ngrams(query: str, n: int) -> list[str]:
    """整词无命中时的退路：中文 n 元组（"一元二次方程的解法" n=3 → 一元二/元二次/...）。"""
    chars = "".join(ch for ch in query if _CJK.match(ch))
    grams: list[str] = []
    for i in range(len(chars) - n + 1):
        g = chars[i : i + n]
        if g not in grams:
            grams.append(g)
    return grams


_CLEAN = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\x20-\x7e\s\u00b0-\u00ff\u2010-\u206f\u0391-\u03c9]")


def _clean_ratio(content: str) -> float:
    """可读字符占比。人教版 PDF 部分页字体映射损坏，抽出来是 ᑓᄼ߆ 一类乱码
    （A2-FONT-SUBSTITUTION-CAVEAT）；这类 chunk 词面命中再多也不是好素材。"""
    if not content:
        return 0.0
    return len(_CLEAN.findall(content)) / len(content)


def _is_toc_chunk(content: str) -> bool:
    """目录页：词面命中多但没有正文（"目 录 第十九章 ... 第二十章 勾股定理 ..."）。"""
    head = "".join(content[:40].split())
    return "目录" in head


def _lexical_score(content: str, terms: list[str]) -> float:
    """命中词占比为主（0.8 权重）+ 出现频次（饱和于 5 次，0.2 权重）。

    这是**词面匹配分，不是 cosine**——量纲不同，所以 lexical 兜底只在
    min_score<=0（聊天呈现层）时启用，Book Engine 的 R1 阈值 0.60 语义不受影响。
    """
    if not terms:
        return 0.0
    hits = [content.count(t) for t in terms]
    coverage = sum(1 for h in hits if h > 0) / len(terms)
    freq = min(sum(hits), 5) / 5
    return round(0.8 * coverage + 0.2 * freq, 4)


async def _search_by_lexical(
    db: AsyncSession, query: str, top_k: int
) -> list[dict]:
    """embedding 不可用（embed 服务宕/模型缺失/向量维度不符）时的词面兜底。

    先用整词 ILIKE 召回；整词无命中再退到中文二元组（要求 >=60% 二元组命中）。
    结果形状与 free_text 完全一致，verified 恒 False、provenance 恒 inferred。
    """

    async def _candidates(terms: list[str]):
        if not terms:
            return []
        clauses = " OR ".join(f"tc.content ILIKE :t{i}" for i in range(len(terms)))
        params: dict = {f"t{i}": f"%{t}%" for i, t in enumerate(terms)}
        params["lim"] = _LEXICAL_CANDIDATE_LIMIT
        return (
            await db.execute(
                sa_text(f"""
            SELECT tc.id, tc.file_id, tc.page_number, tc.char_start, tc.char_end,
                   tc.content, t.subject, t.grade, t.book_name
            FROM textbook_chunks tc
            JOIN textbook_files tf ON tf.id = tc.file_id
            LEFT JOIN textbooks t ON t.id = tf.textbook_id
            WHERE {clauses}
            LIMIT :lim
        """),
                params,
            )
        ).fetchall()

    terms = _lexical_terms(query)
    rows = await _candidates(terms)
    min_cov = 0.0
    if not rows:
        # 4 字以上用三元组（覆盖 >=50%）——二元组太宽："光合作用"的 合作/作用 会
        # 命中物理/英语里任意"作用"；3 字查询只能用二元组，且要求全部命中。
        cjk_len = len(_cjk_ngrams(query, 1))
        if cjk_len >= 4:
            terms, min_cov = _cjk_ngrams(query, 3), 0.5
        else:
            terms, min_cov = _cjk_ngrams(query, 2), 1.0
        rows = await _candidates(terms)

    scored = []
    for r in rows:
        content = r.content or ""
        coverage = sum(1 for t in terms if t in content) / len(terms) if terms else 0.0
        if coverage <= 0 or coverage < min_cov:
            continue
        score = _lexical_score(content, terms)
        if _is_toc_chunk(content):
            score *= 0.5  # 目录页降权：有词无正文
        score = round(score * _clean_ratio(content), 4)  # 乱码页降权
        density = sum(content.count(t) * len(t) for t in terms) / max(len(content), 1)
        scored.append((r, score, density))
    scored.sort(key=lambda x: (x[1], x[2]), reverse=True)

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
            verified=False,
        )
        for rank, (r, score, _density) in enumerate(scored[:top_k], 1)
    ]


async def _search_by_free_text(
    db: AsyncSession,
    query: str,
    top_k: int,
    min_score: float,
    purpose: Optional[str] = None,
    meta: Optional[dict] = None,
) -> Optional[list[dict]]:
    """实时 embed query + 语料库全量 numpy cosine（复用 embed_chunks.embed_text，
    与 chunk 入库时同一模型——否则向量空间不一致，相似度没有意义）。

    返回 None 表示"语义检索不可用"（embed 失败或库内向量维度与 query 不符），
    由调用方决定是否走词面兜底；返回 [] 表示语义检索可用但无结果。
    """
    query_vec, model = await _embed_query(query)
    if query_vec is None:
        logger.warning("search_knowledge_base: query embedding 不可用，语义检索跳过")
        return None
    if meta is not None:
        meta["embedding_model"] = model or LEGACY_MODEL_KEY
    if purpose:
        min_score = max(min_score, min_score_for(purpose, model))

    dim = len(query_vec)
    ids, mat = await _embedding_matrix(db, dim, model)
    if not ids:
        logger.warning(
            "search_knowledge_base: 库内无与 query(%d 维) 同维度的向量"
            "（未入库或 embedding 模型不一致），语义检索不可用",
            dim,
        )
        return None

    q = np.asarray(query_vec, dtype=np.float32)
    qn = float(np.linalg.norm(q))
    if qn == 0:
        return None
    scores = mat @ (q / qn)
    keep = np.nonzero(scores >= min_score)[0]
    order = keep[np.argsort(-scores[keep], kind="stable")][:top_k]
    if order.size == 0:
        return []
    top_ids = [ids[i] for i in order]
    top_scores = {ids[i]: float(scores[i]) for i in order}

    rows = (
        await db.execute(
            sa_text("""
        SELECT tc.id, tc.file_id, tc.page_number, tc.char_start, tc.char_end,
               tc.content, t.subject, t.grade, t.book_name
        FROM textbook_chunks tc
        JOIN textbook_files tf ON tf.id = tc.file_id
        LEFT JOIN textbooks t ON t.id = tf.textbook_id
        WHERE tc.id = ANY(:ids)
    """),
            {"ids": top_ids},
        )
    ).fetchall()
    by_id = {r.id: r for r in rows}

    results: list[dict] = []
    for chunk_id in top_ids:
        r = by_id.get(chunk_id)
        if r is None:  # 缓存与库之间被删——跳过，不伪造
            continue
        results.append(
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
                score=top_scores[chunk_id],
                rank=len(results) + 1,
                verified=False,  # free_text 不经 KU 挂接，没有对应的人工校订机制
            )
        )
    return results


async def search_knowledge_base(
    db: AsyncSession,
    *,
    kc_id: Optional[str] = None,
    query: Optional[str] = None,
    top_k: int = 3,
    min_score: float = 0.0,
    purpose: Optional[str] = None,
) -> dict:
    """Knowledge Hub 检索主入口。

    kc_id 与 query 二选一（不可同时为空，同时给出时 kc_id 优先——复用 A3
    预计算结果，确定性更好、无需实时 embed 调用）。

    min_score：默认 0.0（不过滤，A4 聊天场景的既有行为不变）。Book Engine
    引用教材内容必须传 R1 阈值（Part B spec §1 R1：0.60，"垃圾兜底非质量门"，
    见 outputs/W3-PENDING-ITEMS.md）——过滤在这里做一次，调用方不用各自记住
    阈值数字。

    embedding 不可用时（embed 服务宕/模型缺失/维度不符），free_text 路径在
    min_score<=0 时退到词面检索，返回值额外带 "retrieval": "lexical"。

    purpose（"book"/"chat"，可选）：按打分模型取标定阈值（见 min_score_for）。
    换了 embedding 模型后 cosine 量纲变化，调用方传 purpose 就不用自己记
    每个模型的数字；min_score 仍作为额外下限。free_text 语义结果附带
    "embedding_model"（"legacy" 或侧车模型名），供调用方按模型解释分数。

    返回 {"query_type": "kc_id"|"free_text", "results": [...]}；results 永远是
    列表（找不到内容/embedding 不可用时为空列表，不抛异常——呈现层素材缺失
    不该打断调用方）。每条结果带 "verified" 字段（R3/R4，见 citation_state()）。
    """
    if not kc_id and not query:
        return {"query_type": None, "results": []}

    if kc_id:
        results = await _search_by_kc_id(db, kc_id, top_k, min_score, purpose)
        return {"query_type": "kc_id", "results": results}

    assert query is not None
    meta: dict = {}
    semantic = await _search_by_free_text(db, query, top_k, min_score, purpose, meta)
    if semantic is not None:
        return {"query_type": "free_text", "results": semantic, **meta}
    # 语义检索不可用：仅在不设阈值（聊天呈现层）时走词面兜底——词面分不是 cosine，
    # 不能拿去对 R1 的 0.60 阈值（Book Engine 场景宁缺毋滥，返回空）。
    if min_score > 0 or purpose == "book":
        return {"query_type": "free_text", "results": []}
    lexical = await _search_by_lexical(db, query, top_k)
    return {"query_type": "free_text", "results": lexical, "retrieval": "lexical"}
