"""Exit/stop-loss technical indicators (Chandelier Exit)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from oprim.technical._base import _to_array, _wilder_atr, _wrap


def chandelier_exit(
    highs: np.ndarray | pd.Series,
    lows: np.ndarray | pd.Series,
    closes: np.ndarray | pd.Series,
    *,
    period: int = 22,
    multiplier: float = 3.0,
) -> dict[str, np.ndarray | pd.Series]:
    """Chandelier Exit (trend-following stop loss).

    Mathematical definition:
        atr_t = wilder_atr(high, low, close, period)
        long_exit_t = max(high_{t-period+1}, ..., high_t) - multiplier * atr_t
        short_exit_t = min(low_{t-period+1}, ..., low_t) + multiplier * atr_t

    Uses _wilder_atr from oprim/technical/_base.py (H1 compliant — no import of sibling oprim.atr).
    First `period` positions are NaN.

    Reference: Le Beau (1990s); "Computerized Trading".

    Parameters
    ----------
    highs : array-like
        Bar high prices.
    lows : array-like
        Bar low prices.
    closes : array-like
        Bar close prices.
    period : int
        ATR and rolling extrema period (default 22).
    multiplier : float
        ATR multiplier (default 3.0).

    Returns
    -------
    dict with keys: 'long_exit', 'short_exit'. Each same length as input.

    Raises
    ------
    ValueError
        If lengths mismatch, period <= 0, or multiplier <= 0.
    """
    h_arr, is_series, idx = _to_array(highs)
    l_arr, _, _ = _to_array(lows)
    c_arr, _, _ = _to_array(closes)
    n = len(c_arr)
    if n == 0:
        raise ValueError("closes must not be empty")
    if len(h_arr) != n or len(l_arr) != n:
        raise ValueError("highs, lows, closes must have same length")
    if not isinstance(period, int) or period <= 0:
        raise ValueError(f"period must be a positive integer, got {period!r}")
    if multiplier <= 0:
        raise ValueError(f"multiplier must be positive, got {multiplier!r}")

    atr_series = _wilder_atr(h_arr, l_arr, c_arr, period)

    hs = pd.Series(h_arr)
    ls = pd.Series(l_arr)
    highest_high = hs.rolling(period).max().to_numpy()
    lowest_low = ls.rolling(period).min().to_numpy()

    long_exit = highest_high - multiplier * atr_series
    short_exit = lowest_low + multiplier * atr_series

    def _w(a: np.ndarray) -> np.ndarray | pd.Series:
        return _wrap(a, is_series, idx)

    return {"long_exit": _w(long_exit), "short_exit": _w(short_exit)}
