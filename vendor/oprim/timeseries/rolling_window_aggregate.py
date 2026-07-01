"""A4 — Rolling window aggregate (unified int + time window, multiple agg functions)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_window_aggregate(
    *,
    series: pd.Series | np.ndarray | list[float],
    window: int | str,
    agg: str = "mean",
    quantile_q: float = 0.5,
    min_periods: int | None = None,
) -> pd.Series:
    """Apply rolling window aggregation.

    Parameters
    ----------
    series : input data (numpy auto-converted to pd.Series)
    window : int (fixed) or str (time-based, e.g. "7D")
    agg : one of "mean", "std", "min", "max", "sum", "median", "quantile"
    quantile_q : quantile level (only used when agg="quantile")
    min_periods : minimum observations in window

    Returns
    -------
    pd.Series with rolling aggregate values.
    """
    if isinstance(series, (np.ndarray, list)):
        s = pd.Series(series)
    else:
        s = series

    if isinstance(window, str) and not isinstance(s.index, pd.DatetimeIndex):
        raise ValueError("Time-based window requires DatetimeIndex")

    if min_periods is None:
        min_periods = 1

    roller = s.rolling(window=window, min_periods=min_periods)

    if agg == "mean":
        return roller.mean()
    elif agg == "std":
        return roller.std()
    elif agg == "min":
        return roller.min()
    elif agg == "max":
        return roller.max()
    elif agg == "sum":
        return roller.sum()
    elif agg == "median":
        return roller.median()
    elif agg == "quantile":
        return roller.quantile(quantile_q)
    else:
        raise ValueError(f"Unknown agg: {agg}")
