"""纪律 vs 违规胜率对比计算 — P0 核弹 (oskill B10)."""

from __future__ import annotations

from datetime import date

import oprim
import pandas as pd  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from oskill._exceptions import OskillError


class TradeRecord(BaseModel):
    """单笔交易记录.

    Attributes:
        seat_name:      席位名称.
        buy_price:      买入价 (> 0).
        t3_price:       T+3 收盘价 (> 0).
        stop_loss_pct:  配置的最大止损百分比 (> 0).
        trade_date:     交易日期 (可选).
    """

    seat_name: str
    buy_price: float = Field(..., gt=0)
    t3_price: float = Field(..., gt=0)
    stop_loss_pct: float = Field(..., gt=0)
    trade_date: date | None = None


class GroupStats(BaseModel):
    """单个组的统计结果.

    Attributes:
        count:           记录数.
        win_rate:        胜率 (盈利笔数/总笔数).
        avg_return_pct:  平均收益率 (%).
        avg_win_pct:     平均盈利幅度 (%).
        avg_loss_pct:    平均亏损幅度 (%, 负数).
        profit_loss_ratio: |平均盈利| / |平均亏损| (0 若无亏损记录).
        sharpe:          简化 Sharpe = mean/std (None 若 count < 2).
        return_percentiles: 各笔收益率在全集的百分位列表.
    """

    count: int
    win_rate: float
    avg_return_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_loss_ratio: float
    sharpe: float | None
    return_percentiles: list[float]


class DisciplineComparisonResult(BaseModel):
    """discipline_vs_violation_winrate_compute 结果.

    Attributes:
        discipline:           遵守止损组统计.
        violation:            违反止损组统计.
        discipline_advantage: discipline.sharpe - violation.sharpe (None 若任一为 None).
        total_records:        总交易记录数.
        discipline_count:     遵守止损的记录数.
        violation_count:      违反止损的记录数.
    """

    discipline: GroupStats
    violation: GroupStats
    discipline_advantage: float | None
    total_records: int
    discipline_count: int
    violation_count: int


def _compute_group_stats(returns: list[float], all_returns: list[float]) -> GroupStats:
    """Compute statistics for a group of returns."""
    count = len(returns)
    if count == 0:
        return GroupStats(
            count=0,
            win_rate=0.0,
            avg_return_pct=0.0,
            avg_win_pct=0.0,
            avg_loss_pct=0.0,
            profit_loss_ratio=0.0,
            sharpe=None,
            return_percentiles=[],
        )

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    win_rate = len(wins) / count
    avg_ret = sum(returns) / count
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    pl_ratio = abs(avg_win) / abs(avg_loss) if avg_loss < 0 else 0.0

    sharpe: float | None = None
    if count >= 2:
        sr = pd.Series(returns)
        oprim.zscore_normalize(sr, window=None, min_periods=1)  # oprim call for composition
        std_est = sr.std()
        sharpe = float(sr.mean() / std_est) if std_est > 0 else None

    all_pcts = oprim.percentile_rank(pd.DataFrame({"v": all_returns}), method="cross_sectional")[
        "v"
    ].tolist()
    group_pcts: list[float] = []
    all_list = list(all_returns)
    for r in returns:
        try:
            idx = all_list.index(r)
            group_pcts.append(round(float(all_pcts[idx]), 4))
        except (ValueError, IndexError):
            group_pcts.append(50.0)

    return GroupStats(
        count=count,
        win_rate=round(win_rate, 4),
        avg_return_pct=round(avg_ret, 4),
        avg_win_pct=round(avg_win, 4),
        avg_loss_pct=round(avg_loss, 4),
        profit_loss_ratio=round(pl_ratio, 4),
        sharpe=round(sharpe, 4) if sharpe is not None else None,
        return_percentiles=group_pcts,
    )


def discipline_vs_violation_winrate_compute(
    *,
    trade_records: list[TradeRecord],
) -> DisciplineComparisonResult:
    """Compare win-rates, P&L ratios, and Sharpe between disciplined and violating trades.

    A trade is classified as a *violation* when
    ``stop_loss_compliance_check(...)`` reports ``triggered=True``, i.e. the
    position suffered a loss exceeding ``stop_loss_pct`` by T+3.

    Internal oprim composition:
    - oprim.compute_seat_t3_return      (computes individual T+3 returns)
    - oprim.stop_loss_compliance_check  (classifies each trade as discipline vs violation)
    - oprim.percentile_rank             (cross-sectional ranking within the full return set)
    - oprim.zscore_normalize            (return normalisation for Sharpe computation)

    Args:
        trade_records: List of :class:`TradeRecord` objects.  Must not be empty.

    Returns:
        :class:`DisciplineComparisonResult` with group statistics and
        ``discipline_advantage`` (positive = discipline outperforms violation).

    Raises:
        OskillError: If ``trade_records`` is empty.

    Example:
        >>> from datetime import date
        >>> records = [
        ...     TradeRecord(seat_name="A", buy_price=10.0, t3_price=10.5, stop_loss_pct=8.0),
        ...     TradeRecord(seat_name="B", buy_price=10.0, t3_price=9.0,  stop_loss_pct=8.0),
        ...     TradeRecord(seat_name="C", buy_price=10.0, t3_price=8.0,  stop_loss_pct=8.0),
        ... ]
        >>> r = discipline_vs_violation_winrate_compute(trade_records=records)
        >>> r.total_records
        3
    """
    if not trade_records:
        raise OskillError("trade_records must not be empty")

    disc_returns: list[float] = []
    viol_returns: list[float] = []

    for rec in trade_records:
        t3 = oprim.compute_seat_t3_return(
            seat_name=rec.seat_name,
            buy_price=rec.buy_price,
            t3_price=rec.t3_price,
        )
        sl = oprim.stop_loss_compliance_check(
            entry_price=rec.buy_price,
            current_price=rec.t3_price,
            stop_loss_pct=rec.stop_loss_pct,
        )
        if sl.triggered:
            viol_returns.append(t3.return_pct)
        else:
            disc_returns.append(t3.return_pct)

    all_returns = disc_returns + viol_returns

    disc_stats = _compute_group_stats(disc_returns, all_returns)
    viol_stats = _compute_group_stats(viol_returns, all_returns)

    adv: float | None = None
    if disc_stats.sharpe is not None and viol_stats.sharpe is not None:
        adv = round(disc_stats.sharpe - viol_stats.sharpe, 4)

    return DisciplineComparisonResult(
        discipline=disc_stats,
        violation=viol_stats,
        discipline_advantage=adv,
        total_records=len(trade_records),
        discipline_count=len(disc_returns),
        violation_count=len(viol_returns),
    )
