"""回测资金曲线三段切分分析 (oskill B10)."""

from __future__ import annotations

from typing import Any

import oprim
import pandas as pd  # type: ignore[import-untyped]
from pydantic import BaseModel

from oskill._exceptions import OskillError
from oskill.backtest import market_rules_backtest_run


class SegmentMetrics(BaseModel):
    """单段回测统计.

    Attributes:
        segment:       段名称 (``"train"`` / ``"val"`` / ``"oos"``).
        trade_count:   该段交易笔数.
        final_equity:  段末资金.
        pnl_pct:       段内盈亏率 (%).
        pnl_percentile: 三段中的盈亏率百分位.
    """

    segment: str
    trade_count: int
    final_equity: float
    pnl_pct: float
    pnl_percentile: float


class EquityCurve3SegResult(BaseModel):
    """equity_curve_3seg_compute 结果.

    Attributes:
        train:  训练段统计.
        val:    验证段统计.
        oos:    样本外段统计.
        overfitting_flag: train Sharpe 远超 oos Sharpe 时为 True.
    """

    train: SegmentMetrics
    val: SegmentMetrics
    oos: SegmentMetrics
    overfitting_flag: bool


def equity_curve_3seg_compute(
    *,
    signals: list[dict[str, Any]],
    ohlcv_by_symbol: dict[str, list[dict[str, Any]]],
    market_rules: dict[str, Any],
    initial_capital: float = 1_000_000,
    train_ratio: float = 0.6,
    val_ratio: float = 0.2,
) -> EquityCurve3SegResult:
    """Run a backtest and evaluate equity curve quality across train/val/OOS segments.

    Internal oprim composition:
    - oprim.train_val_oos_splitter  (splits signal list into 60/20/20 temporal segments)
    - oprim.percentile_rank         (cross-sectional ranking of segment PnL)

    Sibling oskill (depth-1):
    - oskill.market_rules_backtest_run  (runs the actual market-rules backtest per segment)
      Note: market_rules_backtest_run does NOT call equity_curve_3seg_compute.

    Args:
        signals:          Ordered signal list (oldest first).
        ohlcv_by_symbol:  OHLCV data keyed by symbol.
        market_rules:     Market rule configuration dict.
        initial_capital:  Starting capital.
        train_ratio:      Train set fraction (default 0.6).
        val_ratio:        Validation set fraction (default 0.2).

    Returns:
        :class:`EquityCurve3SegResult` with per-segment metrics.

    Raises:
        OskillError: If ``signals`` has fewer than 3 elements.

    Example:
        >>> r = equity_curve_3seg_compute(
        ...     signals=[{"symbol": "s", "date": ..., "side": "buy", "size_fraction": 0.1}] * 10,
        ...     ohlcv_by_symbol={}, market_rules={}, initial_capital=1_000_000,
        ... )
        >>> r.train.segment
        'train'
    """
    if len(signals) < 3:
        raise OskillError(f"signals must have ≥ 3 elements, got {len(signals)}")

    split = oprim.train_val_oos_splitter(
        data=signals,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
    )

    segment_data = [("train", split.train), ("val", split.val), ("oos", split.oos)]
    seg_metrics: list[SegmentMetrics] = []

    for seg_name, seg_signals in segment_data:
        if not seg_signals:
            seg_metrics.append(
                SegmentMetrics(
                    segment=seg_name,
                    trade_count=0,
                    final_equity=initial_capital,
                    pnl_pct=0.0,
                    pnl_percentile=50.0,
                )
            )
            continue
        bt = market_rules_backtest_run(
            signals=seg_signals,
            ohlcv_by_symbol=ohlcv_by_symbol,
            market_rules=market_rules,
            initial_capital=initial_capital,
        )
        equity_curve = bt.get("equity_curve", [])
        final_eq = equity_curve[-1][1] if equity_curve else initial_capital
        pnl_pct = (final_eq - initial_capital) / initial_capital * 100
        seg_metrics.append(
            SegmentMetrics(
                segment=seg_name,
                trade_count=len(bt.get("trades", [])),
                final_equity=round(final_eq, 2),
                pnl_pct=round(pnl_pct, 4),
                pnl_percentile=50.0,
            )
        )

    pnl_vals = [s.pnl_pct for s in seg_metrics]
    if len(pnl_vals) >= 2:
        pcts = oprim.percentile_rank(pd.DataFrame({"v": pnl_vals}), method="cross_sectional")[
            "v"
        ].tolist()
        for i, sm in enumerate(seg_metrics):
            sm.pnl_percentile = round(float(pcts[i]), 4)

    train_pnl = seg_metrics[0].pnl_pct
    oos_pnl = seg_metrics[2].pnl_pct
    overfitting_flag = (train_pnl > 0) and (oos_pnl < train_pnl * 0.3)

    return EquityCurve3SegResult(
        train=seg_metrics[0],
        val=seg_metrics[1],
        oos=seg_metrics[2],
        overfitting_flag=overfitting_flag,
    )
