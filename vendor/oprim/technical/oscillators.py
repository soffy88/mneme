"""Oscillator technical indicators (RSI, Stochastic, CCI, Williams %R)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from oprim.technical._base import _to_array, _wrap


def rsi_normalized(
    prices: np.ndarray | pd.Series,
    *,
    period: int = 14,
) -> np.ndarray | pd.Series:
    """Relative Strength Index, normalized to [0, 1].

    Mathematical definition (Wilder smoothing):
        delta_t = P_t - P_{t-1}
        gain_t = max(delta_t, 0)
        loss_t = max(-delta_t, 0)

        avg_gain_0 = mean(gain[0:period])
        avg_gain_t = (avg_gain_{t-1} * (period - 1) + gain_t) / period

        rs_t = avg_gain_t / avg_loss_t
        rsi_t = 1 - 1 / (1 + rs_t)  in [0, 1]

    Standard RSI = rsi_normalized * 100.
    When avg_loss = 0: rsi = 1.0 (pure uptrend, no losses).
    First `period` positions are NaN.
    Input NaN propagates to output.

    Reference: Wilder (1978), "New Concepts in Technical Trading Systems".

    Parameters
    ----------
    prices : array-like
        Time-ordered price series (at least period+1 bars recommended).
    period : int
        Wilder smoothing period (default 14).

    Returns
    -------
    Same type as input, values in [0, 1], NaN for first period positions.

    Raises
    ------
    ValueError
        If prices is empty or period <= 0.
    """
    arr, is_series, idx = _to_array(prices)
    n = len(arr)
    if n == 0:
        raise ValueError("prices must not be empty")
    if not isinstance(period, int) or period <= 0:
        raise ValueError(f"period must be a positive integer, got {period!r}")

    out = np.full(n, np.nan)
    if n < period + 1:
        return _wrap(out, is_series, idx)

    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Seed: SMA of first `period` differences → RSI at index `period`
    avg_gain = float(gains[:period].mean())
    avg_loss = float(losses[:period].mean())
    if avg_loss == 0.0:
        out[period] = 1.0
    else:
        out[period] = 1.0 - 1.0 / (1.0 + avg_gain / avg_loss)

    # Wilder smoothing for remaining positions
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0.0:
            out[i + 1] = 1.0
        else:
            rs = avg_gain / avg_loss
            out[i + 1] = 1.0 - 1.0 / (1.0 + rs)

    return _wrap(out, is_series, idx)


def stochastic_oscillator(
    highs: np.ndarray | pd.Series,
    lows: np.ndarray | pd.Series,
    closes: np.ndarray | pd.Series,
    *,
    k_period: int = 14,
    d_period: int = 3,
    smooth_k: int = 3,
    normalize: bool = True,
) -> dict[str, np.ndarray | pd.Series]:
    """Stochastic Oscillator (%K and %D).

    Mathematical definition:
        raw_K_t = (C_t - min(L, k_period)) / (max(H, k_period) - min(L, k_period))
        K = SMA(raw_K, smooth_k)      [smoothed %K]
        D = SMA(K, d_period)          [signal line]

    Parameters
    ----------
    highs, lows, closes : array-like
        OHLC series of equal length.
    k_period : int
        Lookback period for raw %K. Default 14.
    d_period : int
        SMA period for %D. Default 3.
    smooth_k : int
        SMA period for smoothed %K. Default 3.
    normalize : bool
        If True, values in [0, 1]. If False, values in [0, 100].

    Returns
    -------
    dict with keys: 'k', 'd', 'raw_k'. Each same type as closes.

    Raises
    ------
    ValueError
        If arrays have different lengths or any period is invalid.

    References
    ----------
    Lane, G.C. (1984). Lane's Stochastics. Technical Analysis of Stocks
    and Commodities, 2(3).
    """
    h_arr, is_series, idx = _to_array(highs)
    l_arr, _, _ = _to_array(lows)
    c_arr, _, _ = _to_array(closes)

    n = len(c_arr)
    if n == 0:
        raise ValueError("Input arrays must not be empty")
    if len(h_arr) != n or len(l_arr) != n:
        raise ValueError("highs, lows, closes must have same length")
    for name, val in [("k_period", k_period), ("d_period", d_period), ("smooth_k", smooth_k)]:
        if not isinstance(val, int) or val <= 0:
            raise ValueError(f"{name} must be a positive integer, got {val!r}")

    # Raw %K: rolling min/max
    raw_k = np.full(n, np.nan)
    for i in range(k_period - 1, n):
        low_min = np.min(l_arr[i - k_period + 1 : i + 1])
        high_max = np.max(h_arr[i - k_period + 1 : i + 1])
        denom = high_max - low_min
        if denom == 0:
            raw_k[i] = 0.5  # midpoint when range=0
        else:
            raw_k[i] = (c_arr[i] - low_min) / denom

    # Smoothed %K via SMA
    def _sma(arr: np.ndarray, period: int) -> np.ndarray:
        out = np.full(len(arr), np.nan)
        for i in range(period - 1, len(arr)):
            window = arr[i - period + 1 : i + 1]
            if not np.any(np.isnan(window)):
                out[i] = float(np.mean(window))
        return out

    k_smooth = _sma(raw_k, smooth_k)
    d_line = _sma(k_smooth, d_period)

    if not normalize:
        raw_k = raw_k * 100.0
        k_smooth = k_smooth * 100.0
        d_line = d_line * 100.0

    def _w(a: np.ndarray) -> np.ndarray | pd.Series:
        return _wrap(a, is_series, idx)

    return {"k": _w(k_smooth), "d": _w(d_line), "raw_k": _w(raw_k)}


def cci(
    highs: np.ndarray | pd.Series,
    lows: np.ndarray | pd.Series,
    closes: np.ndarray | pd.Series,
    *,
    period: int = 20,
    constant: float = 0.015,
) -> np.ndarray | pd.Series:
    """Commodity Channel Index (CCI).

    Mathematical definition:
        TP_t = (H_t + L_t + C_t) / 3
        CCI_t = (TP_t - SMA(TP, period)) / (constant * mean_abs_dev(TP, period))

    Parameters
    ----------
    highs, lows, closes : array-like
        OHLC series of equal length.
    period : int
        Rolling window. Default 20.
    constant : float
        Scaling constant (Lambert's 0.015). Default 0.015.

    Returns
    -------
    Same type as closes, NaN for first (period-1) positions.

    Raises
    ------
    ValueError
        If arrays have different lengths or period is invalid.

    References
    ----------
    Lambert, D. (1980). Commodity Channel Index: Tool for Trading Cyclic Trends.
    Commodities Magazine.
    """
    h_arr, is_series, idx = _to_array(highs)
    l_arr, _, _ = _to_array(lows)
    c_arr, _, _ = _to_array(closes)

    n = len(c_arr)
    if n == 0:
        raise ValueError("Input arrays must not be empty")
    if len(h_arr) != n or len(l_arr) != n:
        raise ValueError("highs, lows, closes must have same length")
    if not isinstance(period, int) or period <= 0:
        raise ValueError(f"period must be a positive integer, got {period!r}")

    tp = (h_arr + l_arr + c_arr) / 3.0
    out = np.full(n, np.nan)

    for i in range(period - 1, n):
        tp_window = tp[i - period + 1 : i + 1]
        tp_mean = float(np.mean(tp_window))
        mean_dev = float(np.mean(np.abs(tp_window - tp_mean)))
        if mean_dev == 0:
            out[i] = 0.0
        else:
            out[i] = (tp[i] - tp_mean) / (constant * mean_dev)

    return _wrap(out, is_series, idx)


def williams_r(
    highs: np.ndarray | pd.Series,
    lows: np.ndarray | pd.Series,
    closes: np.ndarray | pd.Series,
    *,
    period: int = 14,
    normalize: bool = True,
) -> np.ndarray | pd.Series:
    """Williams %R momentum oscillator.

    Mathematical definition:
        %R_t = (H_n - C_t) / (H_n - L_n) * (-100)

    where H_n = rolling max of highs, L_n = rolling min of lows over period.

    Parameters
    ----------
    highs, lows, closes : array-like
        OHLC series of equal length.
    period : int
        Lookback period. Default 14.
    normalize : bool
        If True, return values in [0, 1] via 1 - abs(%R)/100.
        If False, return raw values in [-100, 0].

    Returns
    -------
    Same type as closes. NaN for first (period-1) positions.

    Raises
    ------
    ValueError
        If arrays have different lengths or period is invalid.

    References
    ----------
    Williams, L. (1979). How I Made One Million Dollars Last Year Trading
    the Commodity Markets.
    """
    h_arr, is_series, idx = _to_array(highs)
    l_arr, _, _ = _to_array(lows)
    c_arr, _, _ = _to_array(closes)

    n = len(c_arr)
    if n == 0:
        raise ValueError("Input arrays must not be empty")
    if len(h_arr) != n or len(l_arr) != n:
        raise ValueError("highs, lows, closes must have same length")
    if not isinstance(period, int) or period <= 0:
        raise ValueError(f"period must be a positive integer, got {period!r}")

    out = np.full(n, np.nan)
    for i in range(period - 1, n):
        h_max = np.max(h_arr[i - period + 1 : i + 1])
        l_min = np.min(l_arr[i - period + 1 : i + 1])
        denom = h_max - l_min
        if denom == 0:
            raw_r = -50.0
        else:
            raw_r = (h_max - c_arr[i]) / denom * (-100.0)

        if normalize:
            out[i] = 1.0 - abs(raw_r) / 100.0
        else:
            out[i] = raw_r

    return _wrap(out, is_series, idx)
