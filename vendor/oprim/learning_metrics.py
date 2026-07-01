"""学习留存/报告的确定性指标（连续活跃天数、周摘要、日报文案）。oprim 原子操作。

此前内联在 services/cognitive_service（家长日报 daily_report / 周报 weekly_digest），
违反"服务层不写确定性算法/呈现逻辑"。DB 取数仍在服务层；本模块只对取出的数据做纯计算+成文。
（注：这些是确定性 fetch→compute→format，非 LLM/多支柱业务事务，故归 oprim 而非包成 omodul。）
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Sequence


def consecutive_active_days(active_dates: set, today: date) -> int:
    """从今天（或昨天，若今天还没活动）往回数连续活跃日。"""
    streak = 0
    cursor = today if today in active_dates else today - timedelta(days=1)
    while cursor in active_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def weekly_digest_metrics(
    *,
    interactions_7d: Sequence,   # 元素 (occurred_at, knowledge_point, is_correct)
    days_active_7d: int,
    effort_gains_7d: int,
    streak: int,
    active_today: bool,
) -> dict:
    """近 7 天交互 + 连续天数 → 周成长摘要 dict（含 headline 文案）。"""
    n = len(interactions_7d)
    distinct_kcs = len({r[1] for r in interactions_7d})
    n_correct = sum(1 for r in interactions_7d if r[2])
    accuracy = round(n_correct / n, 4) if n else None
    headline = f"本周练了 {n} 道、{distinct_kcs} 个知识点，活跃 {days_active_7d} 天"
    if streak:
        headline += f"，已连续 {streak} 天 🔥"
    return {
        "current_streak": streak,
        "active_today": active_today,
        "n_interactions_7d": n,
        "distinct_kcs_7d": distinct_kcs,
        "accuracy_7d": accuracy,
        "days_active_7d": days_active_7d,
        "effort_gains_7d": effort_gains_7d,
        "headline": headline,
    }


def daily_report_text(
    *,
    day_iso: str,
    n: int,
    distinct_kcs: int,
    correct: int,
    socratic: int,
    streak: int,
    weak_kc_count: int,
) -> str:
    """某天学习活动 → 家长一句话日报（看成长非分数）。"""
    if n == 0:
        return f"{day_iso}：今天还没有学习记录。"
    text = f"{day_iso} 学习日报：练了 {n} 道、覆盖 {distinct_kcs} 个知识点，正确率 {round(correct / n * 100)}%"
    if socratic:
        text += f"，自主攻克 {int(socratic)} 次苏格拉底引导"
    text += f"。当前连续 {streak} 天，薄弱点 {int(weak_kc_count)} 个。"
    return text


__all__ = ["consecutive_active_days", "weekly_digest_metrics", "daily_report_text"]
