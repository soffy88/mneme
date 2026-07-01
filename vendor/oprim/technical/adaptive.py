"""Adaptive technical indicators: KAMA (Kaufman Adaptive Moving Average)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from oprim.technical._base import _to_array, _wrap


def kama(
    prices: np.ndarray | pd.Series,
    *,
    er_period: int = 10,
    fast_period: int = 2,
    slow_period: int = 30,
) -> np.ndarray | pd.Series:
    """Kaufman Adaptive Moving Average (KAMA).

    Adapts its smoothing constant based on the Efficiency Ratio (ER):
    - High ER (trending): uses fast EMA smoothing constant.
    - Low ER (choppy/noisy): uses slow EMA smoothing constant.

    Mathematical definition:
        ER_t = |P_t - P_{t-er_period}| / sum(|P_i - P_{i-1}|, last er_period bars)
        fast_SC = 2/(fast_period+1); slow_SC = 2/(slow_period+1)
        SC_t = (ER_t * (fast_SC - slow_SC) + slow_SC)^2
        KAMA_t = KAMA_{t-1} + SC_t * (P_t - KAMA_{t-1})

    Seeded at KAMA_{er_period} = P_{er_period}. Values before index er_period are NaN.

    Parameters
    ----------
    prices : array-like
        Time-ordered price series.
    er_period : int
        Period for Efficiency Ratio calculation. Default 10.
    fast_period : int
        Fast EMA period (for high efficiency). Default 2.
    slow_period : int
        Slow EMA period (for low efficiency). Default 30.

    Returns
    -------
    Same type as input, NaN for first er_period positions.

    Raises
    ------
    ValueError
        If prices is empty or any period parameter is invalid.

    References
    ----------
    Kaufman, P.J. (1995). Smarter Trading.
    """
    arr, is_series, idx = _to_array(prices)
    n = len(arr)

    if n == 0:
        raise ValueError("prices must not be empty")
    if not isinstance(er_period, int) or er_period <= 0:
        raise ValueError(f"er_period must be a positive integer, got {er_period!r}")
    if not isinstance(fast_period, int) or fast_period <= 0:
        raise ValueError(f"fast_period must be a positive integer, got {fast_period!r}")
    if not isinstance(slow_period, int) or slow_period <= fast_period:
        raise ValueError(
            f"slow_period must be > fast_period, got slow={slow_period}, fast={fast_period}"
        )

    fast_sc = 2.0 / (fast_period + 1)
    slow_sc = 2.0 / (slow_period + 1)

    out = np.full(n, np.nan)
    if n <= er_period:
        return _wrap(out, is_series, idx)

    # Seed
    out[er_period] = arr[er_period]

    for i in range(er_period + 1, n):
        # Efficiency Ratio
        direction = abs(arr[i] - arr[i - er_period])
        volatility = float(np.sum(np.abs(np.diff(arr[i - er_period : i + 1]))))
        er = direction / volatility if volatility > 0 else 0.0

        # Smoothing constant
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2

        out[i] = out[i - 1] + sc * (arr[i] - out[i - 1])

    return _wrap(out, is_series, idx)
