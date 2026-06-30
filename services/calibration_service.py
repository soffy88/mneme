"""BKT 先验校准（item 5：让数据飞轮转起来）。

护城河红线：interaction_events 只增不学是死飞轮。本服务从累积的真实作答里
做经验贝叶斯校准，更新 bkt_priors 并写 calibrated_from_n（此前恒为 0）。

可校准什么：
- p_slip（粗心率）：按 KC 用"已学会后仍答错"的暖样本估计——同一 (student,kc) 第 2 次
  及以后的错误率。与题型基本无关，可按 KC 校准。
- p_guess 强依赖题型（选择 0.25 vs 解答 0.02），而 interaction_events 不含题型，
  无法在不引入偏差的前提下拆分，故本版保留种子 guess（诚实不臆测）。

经验贝叶斯收缩：cal = (n_warm·emp + K·prior) / (n_warm + K)，K 为伪计数，
样本少时贴近种子先验，样本多时贴近经验值。结果 clamp 到 [0.01, 0.40]。
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import BKTPrior, InteractionEvent

_SLIP_MIN, _SLIP_MAX = 0.01, 0.40
_PSEUDO = 10.0   # 伪计数 K
_MIN_WARM = 15   # 暖样本不足则不校准该 KC


async def calibrate_bkt_priors(
    db: AsyncSession,
    *,
    pseudo: float = _PSEUDO,
    min_warm: int = _MIN_WARM,
) -> dict:
    """从 interaction_events 校准各 KC 的 p_slip，更新 bkt_priors。

    Returns {calibrated_kcs, total_warm_events, updated_prior_rows}。
    """
    rows = (await db.execute(
        select(
            InteractionEvent.knowledge_point,
            InteractionEvent.student_id,
            InteractionEvent.occurred_at,
            InteractionEvent.is_correct,
        )
    )).all()

    # 按 (kc) → (student) → 时间序列收集
    by_kc_student: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    for kc, sid, ts, is_correct in rows:
        if kc is None:
            continue
        by_kc_student[kc][sid].append((ts, bool(is_correct)))

    # 暖样本：每个 (student,kc) 第 2 次及以后的作答
    warm_stats: dict[str, list[int]] = {}  # kc → [errors, total]
    for kc, students in by_kc_student.items():
        errors = total = 0
        for _sid, seq in students.items():
            seq.sort(key=lambda x: x[0])
            for _ts, correct in seq[1:]:   # 跳过首次（冷样本）
                total += 1
                if not correct:
                    errors += 1
        if total > 0:
            warm_stats[kc] = [errors, total]

    calibrated_kcs = 0
    total_warm = 0
    updated_rows = 0
    for kc, (errors, total) in warm_stats.items():
        total_warm += total
        if total < min_warm:
            continue
        emp_slip = errors / total
        prior_rows = (await db.execute(
            select(BKTPrior).where(BKTPrior.knowledge_point == kc)
        )).scalars().all()
        if not prior_rows:
            continue
        calibrated_kcs += 1
        for pr in prior_rows:
            prior_slip = pr.p_slip if pr.p_slip is not None else 0.12
            cal = (total * emp_slip + pseudo * prior_slip) / (total + pseudo)
            pr.p_slip = min(_SLIP_MAX, max(_SLIP_MIN, cal))
            pr.calibrated_from_n = (pr.calibrated_from_n or 0) + total
            updated_rows += 1
    await db.flush()
    return {
        "calibrated_kcs": calibrated_kcs,
        "total_warm_events": total_warm,
        "updated_prior_rows": updated_rows,
    }
