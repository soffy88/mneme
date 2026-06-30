"""FSRS 权重优化基础设施（护城河深水区，torch-free）。

背景：fsrs_engine 原只有一个全局默认 Scheduler（人人吃群体默认间隔）。
本服务把累积的真实复习日志变成"数据最优的 FSRS 权重选择"：

- reconstruct_review_logs：从 interaction_events 还原每张卡片的复习序列。
- evaluate_weights：用给定权重重放序列，算"预测可提取性 vs 真实回忆结果"的
  对数损失（log-loss）——越低=该权重的遗忘曲线越贴合这群学生。
- select_best_weights：在候选权重集中选 log-loss 最低者并落库。

说明：完整的梯度拟合 21 维 FSRS 权重需要 torch（不在 Master 技术栈，故不引入）。
本服务做的是**可测的模型选择**：候选可来自 FSRS 默认 + 外部拟合/发布的预设，
由真实数据择优。这已移除"只有全局默认"的瓶颈，让 fsrs_engine 用上数据选出的权重。
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from oprim.fsrs_engine import fsrs_new_card, fsrs_retrievability, fsrs_review
from services.models import FSRSWeights, InteractionEvent

try:
    from fsrs import Rating
except Exception:  # pragma: no cover
    Rating = None  # type: ignore

_EPS = 1e-6
_MIN_REVIEWS = 30  # 复习对不足则不优化（样本太少不可信）


async def reconstruct_review_logs(db: AsyncSession, student_id=None) -> list[list[tuple]]:
    """从 interaction_events 还原复习序列：[[(occurred_at, fsrs_rating, is_correct), ...], ...]，
    每个子列表是一张 (student,kc) 卡片按时间排序的作答。
    student_id 给定时只取该学生（个体拟合用）。"""
    stmt = select(
        InteractionEvent.student_id,
        InteractionEvent.knowledge_point,
        InteractionEvent.occurred_at,
        InteractionEvent.fsrs_rating,
        InteractionEvent.is_correct,
    )
    if student_id is not None:
        stmt = stmt.where(InteractionEvent.student_id == student_id)
    rows = (await db.execute(stmt)).all()
    by_card: dict[tuple, list] = defaultdict(list)
    for sid, kc, ts, rating, correct in rows:
        if kc is None or rating is None:
            continue
        by_card[(sid, kc)].append((ts, int(rating), bool(correct)))
    seqs = []
    for seq in by_card.values():
        if len(seq) >= 2:               # 至少要有一对（首答 + 一次复习）才有评估价值
            seq.sort(key=lambda x: x[0])
            seqs.append(seq)
    return seqs


def evaluate_weights(seqs: Sequence[Sequence[tuple]], parameters: Optional[tuple]) -> tuple[float, int]:
    """重放复习序列，返回 (平均 log-loss, 评估的复习对数)。parameters=None → 默认权重。"""
    if Rating is None:
        return (math.inf, 0)
    # 无效权重（超出 FSRS 合法区间）→ inf，永不被选中（不崩）。
    try:
        fsrs_retrievability(card_dict=fsrs_new_card(), now=None, parameters=parameters)
        if parameters:
            fsrs_review(card_dict=fsrs_new_card(), rating=Rating(3), now=None, parameters=parameters)
    except Exception:
        return (math.inf, 0)
    total_loss = 0.0
    n = 0
    for seq in seqs:
        card = fsrs_new_card()
        for i, (ts, rating, correct) in enumerate(seq):
            if i > 0:
                # 复习前的预测可提取性 vs 真实回忆结果
                r = fsrs_retrievability(card_dict=card, now=ts, parameters=parameters)
                r = min(1.0 - _EPS, max(_EPS, r))
                y = 1.0 if correct else 0.0
                total_loss += -(y * math.log(r) + (1 - y) * math.log(1 - r))
                n += 1
            card = fsrs_review(card_dict=card, rating=Rating(rating), now=ts, parameters=parameters)
    if n == 0:
        return (math.inf, 0)
    return (total_loss / n, n)


async def select_best_weights(
    db: AsyncSession,
    candidates: Sequence[Optional[tuple]],
    *,
    cohort: str = "global",
    min_reviews: int = _MIN_REVIEWS,
) -> dict:
    """在候选权重集中按 log-loss 择优并落库（cohort 维度）。

    candidates 含 None（FSRS 默认）+ 若干预设/外部拟合权重。
    Returns {cohort, n_reviews, default_logloss, best_logloss, improved, stored}。
    """
    seqs = await reconstruct_review_logs(db)
    results = [(c, *evaluate_weights(seqs, c)) for c in candidates]
    # n 各候选相同（同一份序列），取第一个的 n
    n_reviews = results[0][2] if results else 0
    if n_reviews < min_reviews:
        return {"cohort": cohort, "n_reviews": n_reviews, "stored": False,
                "reason": "insufficient_reviews"}

    default_loss = next((loss for (c, loss, _n) in results if c is None), math.inf)
    best_c, best_loss, _ = min(results, key=lambda x: x[1])
    improved = best_c is not None and best_loss < default_loss - _EPS

    # 落库：存最优权重（默认胜出则存 None 表示用默认）
    row = (await db.execute(
        select(FSRSWeights).where(FSRSWeights.cohort == cohort)
    )).scalar_one_or_none()
    params_json = list(best_c) if best_c else None
    if row:
        row.parameters = params_json
        row.logloss = round(best_loss, 6)
        row.n_reviews = n_reviews
    else:
        db.add(FSRSWeights(cohort=cohort, parameters=params_json,
                           logloss=round(best_loss, 6), n_reviews=n_reviews))
    await db.flush()
    return {
        "cohort": cohort,
        "n_reviews": n_reviews,
        "default_logloss": round(default_loss, 6),
        "best_logloss": round(best_loss, 6),
        "improved": improved,
        "stored": True,
    }


def propose_candidates(base: Sequence[float], n: int = 8, jitter: float = 0.08, seed: int = 0) -> list[tuple]:
    """围绕基准权重做小幅扰动生成候选（torch-free 随机搜索）。

    完整 21 维梯度拟合需 torch（不在 Master 技术栈）；此处用确定性随机搜索做轻量探索，
    由 evaluate_weights 在真实日志上择优。未来若有 torch 拟合权重，作为候选并入即可。
    """
    import random as _random
    rng = _random.Random(seed)
    out: list[tuple] = []
    for _ in range(max(0, n)):
        out.append(tuple(max(1e-4, p * (1.0 + rng.uniform(-jitter, jitter))) for p in base))
    return out


def fit_weights(seqs, base: Optional[Sequence[float]] = None, maxiter: int = 40):
    """导数无关拟合（scipy Powell）最小化 log-loss。不引入 torch（前向不可微）。

    返回 (best_params|None, best_loss, default_loss)。best_params=None 表示没拟合出
    优于默认的权重（用默认）。无效权重在目标里记大惩罚，优化器自然避开。
    """
    try:
        import numpy as np
        from scipy.optimize import minimize
        from fsrs import Scheduler
    except Exception:
        base_loss, _ = evaluate_weights(seqs, None)
        return (None, base_loss, base_loss)

    if base is None:
        base = list(Scheduler().parameters)
    default_loss, n = evaluate_weights(seqs, None)
    if n == 0:
        return (None, default_loss, default_loss)

    def obj(x):
        loss, _ = evaluate_weights(seqs, tuple(float(v) for v in x))
        return loss if math.isfinite(loss) else 1e6

    res = minimize(obj, np.array(base, dtype=float), method="Powell",
                   options={"maxiter": maxiter, "xtol": 1e-3, "ftol": 1e-3})
    best = tuple(float(v) for v in np.atleast_1d(res.x))
    best_loss, _ = evaluate_weights(seqs, best)
    if math.isfinite(best_loss) and best_loss < default_loss - _EPS:
        return (best, best_loss, default_loss)
    return (None, default_loss, default_loss)


async def _store_weights(db: AsyncSession, cohort: str, params, logloss: float, n: int) -> None:
    row = (await db.execute(
        select(FSRSWeights).where(FSRSWeights.cohort == cohort))).scalar_one_or_none()
    pj = list(params) if params else None
    if row:
        row.parameters, row.logloss, row.n_reviews = pj, round(logloss, 6), n
    else:
        db.add(FSRSWeights(cohort=cohort, parameters=pj, logloss=round(logloss, 6), n_reviews=n))
    await db.flush()


async def fit_and_store_weights(
    db: AsyncSession, *, cohort: str = "global", student_id=None,
    min_reviews: int = _MIN_REVIEWS, maxiter: int = 40,
) -> dict:
    """拟合并落库某 cohort 的 FSRS 权重（student_id 给定则按个体日志拟合）。"""
    seqs = await reconstruct_review_logs(db, student_id=student_id)
    _, n = evaluate_weights(seqs, None)
    if n < min_reviews:
        return {"cohort": cohort, "n_reviews": n, "stored": False, "reason": "insufficient_reviews"}
    best, best_loss, default_loss = fit_weights(seqs, maxiter=maxiter)
    await _store_weights(db, cohort, best, best_loss, n)
    return {"cohort": cohort, "n_reviews": n, "default_logloss": round(default_loss, 6),
            "best_logloss": round(best_loss, 6), "improved": best is not None, "stored": True}


async def load_cohort_weights(db: AsyncSession, cohort: str = "global") -> Optional[tuple]:
    """读取该 cohort 的已优化 FSRS 权重；无则 None（用默认）。"""
    row = (await db.execute(
        select(FSRSWeights.parameters).where(FSRSWeights.cohort == cohort)
    )).scalar_one_or_none()
    return tuple(row) if row else None


async def load_weights_for_student(db: AsyncSession, student_id) -> Optional[tuple]:
    """个体优先：先 student:{id} 个性化权重，无则 global，再无则默认（None）。"""
    w = await load_cohort_weights(db, cohort=f"student:{student_id}")
    if w is not None:
        return w
    return await load_cohort_weights(db, cohort="global")
