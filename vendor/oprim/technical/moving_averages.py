"""Moving average technical indicators (SMA, EMA, VWAP, MACD)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from oprim.technical._base import _ema_recursive, _to_array, _wrap


def sma(prices: np.ndarray | pd.Series, window: int) -> np.ndarray | pd.Series:
    """Simple Moving Average.

    Mathematical definition:
        SMA_t = (1/N) * sum(P_{t-N+1}, ..., P_t)

    First (window-1) positions are NaN.
    Input NaN values propagate to output.
    Preserves input type: ndarray -> ndarray, Series -> Series (index preserved).

    Reference: Standard finance textbook definition (Wilder, 1978).

    Parameters
    ----------
    prices : array-like
        Time-ordered price series.
    window : int
        Rolling window size (must be 1 <= window <= len(prices)).

    Returns
    -------
    Same type as input, length == len(prices).

    Raises
    ------
    ValueError
        If prices is empty, window <= 0, or window > len(prices).
    """
    arr, is_series, idx = _to_array(prices)
    n = len(arr)
    if n == 0:
        raise ValueError("prices must not be empty")
    if not isinstance(window, int) or window <= 0:
        raise ValueError(f"window must be a positive integer, got {window!r}")
    if window > n:
        raise ValueError(f"window ({window}) exceeds prices length ({n})")

    if is_series:
        result = pd.Series(arr, index=idx).rolling(window).mean()
        return result

    out = np.full(n, np.nan)
    for t in range(window - 1, n):
        out[t] = arr[t - window + 1 : t + 1].mean()
    return out


def ema(
    prices: np.ndarray | pd.Series,
    window: int,
    *,
    adjust: bool = False,
) -> np.ndarray | pd.Series:
    """Exponential Moving Average.

    Mathematical definition (adjust=False, recursive):
        alpha = 2 / (window + 1)
        EMA_0 = P_0
        EMA_t = alpha * P_t + (1 - alpha) * EMA_{t-1}

    Mathematical definition (adjust=True, weighted):
        EMA_t = sum(w_i * P_{t-i}) / sum(w_i),  w_i = (1 - alpha)^i

    Matches pd.Series.ewm(span=window, adjust=<adjust>).mean() exactly.
    First value is P_0 (not NaN) for adjust=False.

    Reference: Pandas EMA documentation; standard finance textbook.

    Parameters
    ----------
    prices : array-like
        Time-ordered price series.
    window : int
        EMA span parameter (alpha = 2 / (window + 1)).
    adjust : bool
        If False (default), use recursive formula.
        If True, use weighted/adjusted formula.

    Returns
    -------
    Same type as input, length == len(prices).

    Raises
    ------
    ValueError
        If prices is empty or window <= 0.
    """
    arr, is_series, idx = _to_array(prices)
    n = len(arr)
    if n == 0:
        raise ValueError("prices must not be empty")
    if not isinstance(window, int) or window <= 0:
        raise ValueError(f"window must be a positive integer, got {window!r}")

    s = pd.Series(arr)
    result_arr = s.ewm(span=window, adjust=adjust).mean().to_numpy()
    return _wrap(result_arr, is_series, idx)


def vwap(
    prices: np.ndarray | pd.Series,
    volumes: np.ndarray | pd.Series,
    window: int | None = None,
) -> np.ndarray | pd.Series:
    """Volume Weighted Average Price.

    Mathematical definition:
        VWAP_t = sum(P_i * V_i, i in window) / sum(V_i, i in window)

    If window is None: cumulative VWAP from t=0.
    If window is int: rolling VWAP over last `window` bars.
    Returns NaN where total volume is zero or window not yet filled.

    Reference: Berkowitz, Logue, Noser (1988); standard market microstructure.

    Parameters
    ----------
    prices : array-like
        Time-ordered price series.
    volumes : array-like
        Volume at each bar (same length as prices, non-negative).
    window : int or None
        Rolling window (None = cumulative).

    Returns
    -------
    Same type as prices input, length == len(prices).

    Raises
    ------
    ValueError
        If lengths mismatch, volumes contain negatives, or window is invalid.
    """
    p_arr, is_series, idx = _to_array(prices)
    v_arr, _, _ = _to_array(volumes)
    n = len(p_arr)
    if n == 0:
        raise ValueError("prices must not be empty")
    if len(v_arr) != n:
        raise ValueError(f"prices and volumes must have same length: {n} vs {len(v_arr)}")
    if np.any(v_arr < 0):
        raise ValueError("volumes must be non-negative")
    if window is not None:
        if not isinstance(window, int) or window <= 0:
            raise ValueError(f"window must be a positive integer, got {window!r}")
        if window > n:
            raise ValueError(f"window ({window}) exceeds prices length ({n})")

    pv = p_arr * v_arr
    out = np.full(n, np.nan)

    if window is None:
        cum_pv = np.cumsum(pv)
        cum_v = np.cumsum(v_arr)
        mask = cum_v > 0
        out[mask] = cum_pv[mask] / cum_v[mask]
    else:
        for t in range(window - 1, n):
            slice_v = v_arr[t - window + 1 : t + 1]
            slice_pv = pv[t - window + 1 : t + 1]
            sv = slice_v.sum()
            if sv > 0:
                out[t] = slice_pv.sum() / sv

    return _wrap(out, is_series, idx)


def macd(
    prices: np.ndarray | pd.Series,
    *,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> dict[str, np.ndarray | pd.Series]:
    """MACD (Moving Average Convergence/Divergence).

    Mathematical definition:
        EMA_fast = ema(prices, fast_period, adjust=False)
        EMA_slow = ema(prices, slow_period, adjust=False)
        MACD = EMA_fast - EMA_slow
        Signal = ema(MACD, signal_period, adjust=False)
        Histogram = MACD - Signal

    Uses _ema_recursive helper (H1 compliant — no import of sibling oprim.ema).

    Reference: Appel (1979); standard TA textbook.

    Parameters
    ----------
    prices : array-like
        Time-ordered price series.
    fast_period : int
        Fast EMA period (default 12). Must be < slow_period.
    slow_period : int
        Slow EMA period (default 26).
    signal_period : int
        Signal EMA period (default 9).

    Returns
    -------
    dict with keys 'macd', 'signal', 'histogram'; each same length as input.

    Raises
    ------
    ValueError
        If fast_period >= slow_period, or any period is non-positive.
    """
    for name, val in [("fast_period", fast_period), ("slow_period", slow_period),
                      ("signal_period", signal_period)]:
        if not isinstance(val, int) or val <= 0:
            raise ValueError(f"{name} must be a positive integer, got {val!r}")
    if fast_period >= slow_period:
        raise ValueError(
            f"fast_period ({fast_period}) must be less than slow_period ({slow_period})"
        )

    arr, is_series, idx = _to_array(prices)
    n = len(arr)
    if n == 0:
        raise ValueError("prices must not be empty")

    fast_ema = _ema_recursive(arr, fast_period)
    slow_ema = _ema_recursive(arr, slow_period)
    macd_line = fast_ema - slow_ema
    signal_line = _ema_recursive(macd_line, signal_period)
    histogram = macd_line - signal_line

    if is_series:
        return {
            "macd": pd.Series(macd_line, index=idx),
            "signal": pd.Series(signal_line, index=idx),
            "histogram": pd.Series(histogram, index=idx),
        }
    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}
