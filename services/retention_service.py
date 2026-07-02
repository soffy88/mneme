"""留存三指标聚合（T.2，登顶路线第 1 步实证地基）。

全体聚合、无 PII（输出不含任何 student_id），供 GET /v1/moat/retention-metrics。
三指标：D7 留存 / 到期复习完成率 / 保留探针校准（实测召回 vs FSRS 预测 R）。
样本不足时 value 返回 None + n，绝不编数。数值一律 round 4 位。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.models import InteractionEvent, InteractionSource, KCMastery
from services.review_service import _parse_card_ts

_D7_COHORT_WINDOW_DAYS = 56  # 近 8 周注册（首次交互）的学生构成 cohort
_D7_MIN_AGE_DAYS = 8  # 第 7±1 天窗口须已完整过去才可判定
_COMPLETION_WINDOW_DAYS = 14  # 到期复习完成率统计窗口
_PROBE_BUCKETS: Tuple[Tuple[float, float], ...] = ((0.0, 0.5), (0.5, 0.8), (0.8, 1.0))


async def d7_retention(db: AsyncSession, now: Optional[datetime] = None) -> dict:
    """D7 留存（近 8 周窗口）。

    口径：锚点 = 学生首次 interaction_event（注册未必开始学习，首次交互更贴近激活）；
    cohort = 首次交互落在 [now-56d, now-8d] 的学生（第 8 天边界已完整过去，可判定）；
    留存 = 在 [首次+6d, 首次+8d) 即第 7±1 天仍有 interaction_events。
    value = 留存数/cohort 数；cohort 为空返回 None + n=0。
    """
    now = now or datetime.now(timezone.utc)
    firsts = (
        await db.execute(
            select(InteractionEvent.student_id, func.min(InteractionEvent.occurred_at))
            .where(InteractionEvent.student_id.is_not(None))
            .group_by(InteractionEvent.student_id)
        )
    ).all()
    lo = now - timedelta(days=_D7_COHORT_WINDOW_DAYS)
    hi = now - timedelta(days=_D7_MIN_AGE_DAYS)
    cohort = [(sid, first) for sid, first in firsts if lo <= first <= hi]
    if not cohort:
        return {"value": None, "n": 0}
    retained = 0
    for sid, first in cohort:
        cnt = (
            await db.execute(
                select(func.count())
                .select_from(InteractionEvent)
                .where(InteractionEvent.student_id == sid)
                .where(InteractionEvent.occurred_at >= first + timedelta(days=6))
                .where(InteractionEvent.occurred_at < first + timedelta(days=8))
            )
        ).scalar() or 0
        if cnt:
            retained += 1
    return {"value": round(retained / len(cohort), 4), "n": len(cohort)}


async def review_completion_rate(
    db: AsyncSession, now: Optional[datetime] = None
) -> dict:
    """到期复习完成率（近 14 天）。

    口径（用 due 与 interaction_events 对齐的近似）：
    - 分子 = 近 14 天内发生过 source='review' 交互的 (student, kc, 日) 组合数。
      复习队列只发到期卡，故 review 交互 ≈ 完成一次到期复习；提交作答与看答案
      （reveal，记 Again）都算"当日实际被复习"；probe 不计入（探针卡本未到期）。
    - 分母 = 分子 + "至今未复习、当前 due 落在近 14 天内"的 (student, kc) 数。
      复习会把 due 推进到未来，所以 due 仍停留在过去 = 到期后一直没复习；
      窗口内已复习过的 (student, kc) 不重复计入欠账（学习步可能当日再次到期）。
    - 近似语义：错过当日、后来补上的复习按补复习当日计为完成。
    value = 分子/分母；分母为 0 返回 None + n=0。
    """
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=_COMPLETION_WINDOW_DAYS)
    rows = (
        await db.execute(
            select(
                InteractionEvent.student_id,
                InteractionEvent.knowledge_point,
                InteractionEvent.occurred_at,
            )
            .where(InteractionEvent.source == InteractionSource.review)
            .where(InteractionEvent.occurred_at >= since)
            .where(InteractionEvent.occurred_at <= now)
        )
    ).all()
    completed = {(sid, kc, ts.date()) for sid, kc, ts in rows}
    completed_pairs = {(sid, kc) for sid, kc, _ in completed}

    cards = (
        await db.execute(
            select(
                KCMastery.student_id,
                KCMastery.knowledge_point,
                KCMastery.fsrs_card_json,
            ).where(KCMastery.fsrs_card_json.is_not(None))
        )
    ).all()
    overdue = 0
    for sid, kc, card in cards:
        if (sid, kc) in completed_pairs:
            continue
        if _parse_card_ts(card.get("last_review")) is None:
            continue  # 从未复习过的新卡不算复习欠账（由新学路径处理）
        due = _parse_card_ts(card.get("due"))
        if due is not None and since <= due <= now:
            overdue += 1

    denom = len(completed) + overdue
    if denom == 0:
        return {"value": None, "n": 0}
    return {"value": round(len(completed) / denom, 4), "n": denom}


def _calibration_agg(pairs: Sequence[Tuple[float, bool]]) -> dict:
    n = len(pairs)
    if n == 0:
        return {"predicted_r_mean": None, "actual_recall": None, "n": 0}
    return {
        "predicted_r_mean": round(sum(p for p, _ in pairs) / n, 4),
        "actual_recall": round(sum(1.0 for _, c in pairs if c) / n, 4),
        "n": n,
    }


async def probe_calibration(db: AsyncSession) -> dict:
    """30 天保留抽测校准：全部 source='probe' 事件的预测 R vs 实测召回。

    口径：predicted_r = 作答当刻 FSRS 预测可提取性（落事件时冻结）；
    actual_recall = 实测正确率（看答案=召回失败记 False）。整体 + 按
    predicted_r 分桶（0-0.5 / 0.5-0.8 / 0.8-1.0，末桶含 1.0）。
    """
    rows = (
        await db.execute(
            select(InteractionEvent.predicted_r, InteractionEvent.is_correct)
            .where(InteractionEvent.source == InteractionSource.probe)
            .where(InteractionEvent.predicted_r.is_not(None))
        )
    ).all()
    pairs = [(float(p), bool(c)) for p, c in rows]
    buckets = {}
    for lo, hi in _PROBE_BUCKETS:
        in_bucket = [
            (p, c) for p, c in pairs if lo <= p < hi or (hi == 1.0 and p == 1.0)
        ]
        buckets[f"{lo}-{hi}"] = _calibration_agg(in_bucket)
    return {**_calibration_agg(pairs), "buckets": buckets}


async def retention_metrics(db: AsyncSession, now: Optional[datetime] = None) -> dict:
    """三留存指标汇总（聚合无 PII）。"""
    now = now or datetime.now(timezone.utc)
    return {
        "d7_retention": await d7_retention(db, now=now),
        "review_completion_rate": await review_completion_rate(db, now=now),
        "probe_calibration": await probe_calibration(db),
    }
