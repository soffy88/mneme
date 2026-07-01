"""oprim.backtest_stat — Single deterministic backtest statistics computation.

3O layer: oprim (single atomic computation, pure stats, no LLM).
Computes standard backtest performance metrics from returns series.
A17: deterministic, reproducible.
"""

from __future__ import annotations
import numpy as np


def backtest_stat(
    *,
    returns: list[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> dict:
    """Compute backtest performance statistics from a returns series.

    returns: list of period returns (e.g. daily)
    Returns: {
        total_return, annualized_return, annualized_volatility,
        sharpe_ratio, max_drawdown, win_rate, n_periods,
    }
    """
    r = np.asarray(returns, dtype=float)
    n = len(r)

    if n == 0:
        return {
            "total_return": 0.0,
            "annualized_return": 0.0,
            "annualized_volatility": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "n_periods": 0,
        }

    total_return = float(np.prod(1 + r) - 1)
    annualized_return = float((1 + total_return) ** (periods_per_year / n) - 1)
    annualized_volatility = float(np.std(r, ddof=1) * np.sqrt(periods_per_year)) if n > 1 else 0.0
    rf_daily = risk_free_rate / periods_per_year
    excess = r - rf_daily
    sharpe_ratio = (
        float(np.mean(excess) / np.std(excess, ddof=1) * np.sqrt(periods_per_year))
        if n > 1 and np.std(excess, ddof=1) > 0
        else 0.0
    )

    # Max drawdown from cumulative returns
    cumulative = np.cumprod(1 + r)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - running_max) / running_max
    max_drawdown = float(np.min(drawdowns))

    win_rate = float(np.mean(r > 0))

    return {
        "total_return": total_return,
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_volatility,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": max_drawdown,
        "win_rate": win_rate,
        "n_periods": n,
    }
