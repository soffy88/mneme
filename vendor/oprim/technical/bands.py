"""Band technical indicators (Bollinger Bands, Donchian Channel, Keltner Channels)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from oprim.technical._base import _ema_recursive, _to_array, _wilder_atr, _wrap


def bollinger_bands(
    prices: np.ndarray | pd.Series,
    *,
    window: int = 20,
    num_std: float = 2.0,
) -> dict[str, np.ndarray | pd.Series]:
    """Bollinger Bands.

    Mathematical definition:
        middle = sma(prices, window)
        std = rolling_std(prices, window, ddof=0)   # population std
        upper = middle + num_std * std
        lower = middle - num_std * std
        bandwidth = (upper - lower) / middle
        percent_b = (price - lower) / (upper - lower)

    Uses **population std (ddof=0)**. When std=0 (constant price):
    bandwidth=0, percent_b=NaN (avoid div-by-zero).

    First (window-1) positions are NaN.
    Input NaN propagates to output.

    Reference: Bollinger (2002), "Bollinger on Bollinger Bands".

    Parameters
    ----------
    prices : array-like
        Time-ordered price series.
    window : int
        Rolling window (default 20).
    num_std : float
        Number of standard deviations for bands (default 2.0).

    Returns
    -------
    dict with keys: 'upper', 'middle', 'lower', 'bandwidth', 'percent_b'.
    Each value is the same type and length as input.

    Raises
    ------
    ValueError
        If prices is empty, window <= 0, or num_std <= 0.
    """
    arr, is_series, idx = _to_array(prices)
    n = len(arr)
    if n == 0:
        raise ValueError("prices must not be empty")
    if not isinstance(window, int) or window <= 0:
        raise ValueError(f"window must be a positive integer, got {window!r}")
    if num_std <= 0:
        raise ValueError(f"num_std must be positive, got {num_std!r}")

    s = pd.Series(arr)
    middle = s.rolling(window).mean().to_numpy()
    std = s.rolling(window).std(ddof=0).to_numpy()
    upper = middle + num_std * std
    lower = middle - num_std * std

    bw = np.full(n, np.nan)
    pct_b = np.full(n, np.nan)
    band_width = upper - lower
    mask = np.isfinite(middle) & (band_width > 0)
    bw[mask] = band_width[mask] / middle[mask]
    pct_b[mask] = (arr[mask] - lower[mask]) / band_width[mask]

    def _w(a: np.ndarray) -> np.ndarray | pd.Series:
        return _wrap(a, is_series, idx)

    return {
        "upper": _w(upper),
        "middle": _w(middle),
        "lower": _w(lower),
        "bandwidth": _w(bw),
        "percent_b": _w(pct_b),
    }


def donchian_channel(
    highs: np.ndarray | pd.Series,
    lows: np.ndarray | pd.Series,
    *,
    window: int = 20,
) -> dict[str, np.ndarray | pd.Series]:
    """Donchian Channel (price range breakout indicator).

    Mathematical definition:
        upper_t = max(high_{t-window+1}, ..., high_t)
        lower_t = min(low_{t-window+1}, ..., low_t)
        middle_t = (upper_t + lower_t) / 2

    First (window-1) positions are NaN.

    Reference: Donchian (1960s); standard turtle trading reference.

    Parameters
    ----------
    highs : array-like
        Rolling highs series.
    lows : array-like
        Rolling lows series.
    window : int
        Lookback period (default 20).

    Returns
    -------
    dict with keys: 'upper', 'middle', 'lower'.

    Raises
    ------
    ValueError
        If lengths mismatch or window <= 0.
    """
    h_arr, is_series, idx = _to_array(highs)
    l_arr, _, _ = _to_array(lows)
    n = len(h_arr)
    if n == 0:
        raise ValueError("highs must not be empty")
    if len(l_arr) != n:
        raise ValueError(f"highs and lows must have same length: {n} vs {len(l_arr)}")
    if not isinstance(window, int) or window <= 0:
        raise ValueError(f"window must be a positive integer, got {window!r}")

    hs = pd.Series(h_arr)
    ls = pd.Series(l_arr)
    upper = hs.rolling(window).max().to_numpy()
    lower = ls.rolling(window).min().to_numpy()
    middle = (upper + lower) / 2.0

    def _w(a: np.ndarray) -> np.ndarray | pd.Series:
        return _wrap(a, is_series, idx)

    return {"upper": _w(upper), "middle": _w(middle), "lower": _w(lower)}


def keltner_channels(
    highs: np.ndarray | pd.Series,
    lows: np.ndarray | pd.Series,
    closes: np.ndarray | pd.Series,
    *,
    ema_period: int = 20,
    atr_period: int = 10,
    multiplier: float = 2.0,
) -> dict[str, np.ndarray | pd.Series]:
    """Keltner Channels volatility-based envelope.

    Mathematical definition:
        middle_t = EMA(close, ema_period)
        atr_t    = Wilder ATR(high, low, close, atr_period)
        upper_t  = middle_t + multiplier * atr_t
        lower_t  = middle_t - multiplier * atr_t

    Parameters
    ----------
    highs, lows, closes : array-like
        OHLC series of equal length.
    ema_period : int
        EMA period for middle band. Default 20.
    atr_period : int
        ATR period for channel width. Default 10.
    multiplier : float
        ATR multiplier. Default 2.0.

    Returns
    -------
    dict with keys: 'upper', 'middle', 'lower'. Each same type as closes.

    Raises
    ------
    ValueError
        If arrays have different lengths or parameters are invalid.

    References
    ----------
    Keltner, C.W. (1960). How to Make Money in Commodities.
    Chester, L. (updated): modern EMA-ATR version.
    """
    h_arr, is_series, idx = _to_array(highs)
    l_arr, _, _ = _to_array(lows)
    c_arr, _, _ = _to_array(closes)

    n = len(c_arr)
    if n == 0:
        raise ValueError("Input arrays must not be empty")
    if len(h_arr) != n or len(l_arr) != n:
        raise ValueError("highs, lows, closes must have same length")
    for name, val in [("ema_period", ema_period), ("atr_period", atr_period)]:
        if not isinstance(val, int) or val <= 0:
            raise ValueError(f"{name} must be a positive integer, got {val!r}")
    if multiplier <= 0:
        raise ValueError(f"multiplier must be positive, got {multiplier!r}")

    middle = _ema_recursive(c_arr, ema_period)
    atr = _wilder_atr(h_arr, l_arr, c_arr, atr_period)

    upper = middle + multiplier * atr
    lower = middle - multiplier * atr

    def _w(a: np.ndarray) -> np.ndarray | pd.Series:
        return _wrap(a, is_series, idx)

    return {"middle": _w(middle), "upper": _w(upper), "lower": _w(lower)}
