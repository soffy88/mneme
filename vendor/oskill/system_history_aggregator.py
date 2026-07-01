"""系统历史聚合 — 审计条目状态机回溯 + 百分位排名 (oskill B10)."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import oprim
import pandas as pd  # type: ignore[import-untyped]
from obase.audit import AuditEntry
from pydantic import BaseModel


class ActionFreqRow(BaseModel):
    """单个 action 类型的频率统计.

    Attributes:
        action:      操作类型 (如 "approve", "delete").
        count:       出现次数.
        pct_rank:    在所有 action 频率中的百分位.
        zscore:      频率 z-score.
    """

    action: str
    count: int
    pct_rank: float
    zscore: float


class SystemHistoryReport(BaseModel):
    """system_history_aggregator 结果.

    Attributes:
        action_freq:    各 action 类型频率与排名.
        daily_activity: 每日活动量 {date_str: count}.
        peak_day:       活动量最高的日期.
        unique_actors:  不同操作者数量.
        unique_actions: 不同操作类型数量.
    """

    action_freq: list[ActionFreqRow]
    daily_activity: dict[str, int]
    peak_day: date | None
    unique_actors: int
    unique_actions: int


def system_history_aggregator(
    *,
    audit_entries: list[AuditEntry],
    lookback_days: int = 30,
) -> SystemHistoryReport:
    """Aggregate audit entries into an action-frequency report with percentile ranking.

    Internal oprim composition:
    - oprim.percentile_rank    (cross-sectional ranking of action frequencies)
    - oprim.zscore_normalize   (z-score of action frequencies for anomaly detection)

    obase composition:
    - obase.audit.AuditEntry  (typed input model from obase.audit)

    Args:
        audit_entries: Pre-fetched audit entries.  May be empty (returns zeroed report).
        lookback_days: Window for daily activity aggregation.

    Returns:
        :class:`SystemHistoryReport`.

    Example:
        >>> from obase.audit import format_audit_entry
        >>> entries = [format_audit_entry(actor="u1", action="approve",
        ...             resource_type="trade", resource_id="t1")]
        >>> r = system_history_aggregator(audit_entries=entries)
        >>> r.unique_actors == 1
        True
    """
    if not audit_entries:
        return SystemHistoryReport(
            action_freq=[],
            daily_activity={},
            peak_day=None,
            unique_actors=0,
            unique_actions=0,
        )

    cutoff = date.today() - timedelta(days=lookback_days)
    recent = [e for e in audit_entries if e.timestamp.date() >= cutoff]
    action_counts = Counter(e.action for e in recent)
    daily: Counter[str] = Counter()
    for e in recent:
        daily[str(e.timestamp.date())] += 1

    actions = list(action_counts.keys())
    counts = list(action_counts.values())

    if len(counts) >= 2:
        cnt_sr = pd.Series(counts, dtype=float)
        pct_vals = oprim.percentile_rank(pd.DataFrame({"v": counts}), method="cross_sectional")[
            "v"
        ].tolist()
        z_vals = oprim.zscore_normalize(cnt_sr, window=None, min_periods=1).fillna(0.0).tolist()
    else:
        pct_vals = [50.0] * len(counts)
        z_vals = [0.0] * len(counts)

    freq_rows = [
        ActionFreqRow(
            action=actions[i],
            count=counts[i],
            pct_rank=round(float(pct_vals[i]), 4),
            zscore=round(float(z_vals[i]), 4),
        )
        for i in range(len(actions))
    ]
    freq_rows.sort(key=lambda r: r.count, reverse=True)

    peak_day_str = daily.most_common(1)[0][0] if daily else None
    peak_day = date.fromisoformat(peak_day_str) if peak_day_str else None

    unique_actors = len({e.actor for e in recent})
    unique_actions = len(action_counts)

    return SystemHistoryReport(
        action_freq=freq_rows,
        daily_activity=dict(daily),
        peak_day=peak_day,
        unique_actors=unique_actors,
        unique_actions=unique_actions,
    )
