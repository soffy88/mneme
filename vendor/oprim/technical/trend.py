"""Trend-following technical indicators: ATR series, ADX series, SuperTrend."""

from __future__ import annotations

import numpy as np
import pandas as pd

from oprim.technical._base import _to_array, _wilder_atr, _wrap


def atr_series(
    highs: np.ndarray | pd.Series,
    lows: np.ndarray | pd.Series,
    closes: np.ndarray | pd.Series,
    *,
    period: int = 14,
) -> np.ndarray | pd.Series:
    """Average True Range as a full series (Wilder smoothing).

    Mathematical definition:
        TR_t = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)
        ATR_t = (ATR_{t-1} * (period - 1) + TR_t) / period  (Wilder)

    First (period) positions are NaN; series starts at index period+1.

    Parameters
    ----------
    highs, lows, closes : array-like
        OHLC series of equal length.
    period : int
        Wilder smoothing period (default 14).

    Returns
    -------
    Same type as closes, values are ATR, NaN for warmup bars.

    Raises
    ------
    ValueError
        If arrays have different lengths or period <= 0.

    References
    ----------
    Wilder, J.W. (1978). New Concepts in Technical Trading Systems.
    """
    h_arr, is_series, idx = _to_array(highs)
    l_arr, _, _ = _to_array(lows)
    c_arr, _, _ = _to_array(closes)

    n = len(c_arr)
    if n == 0:
        raise ValueError("Input arrays must not be empty")
    if len(h_arr) != n or len(l_arr) != n:
        raise ValueError("highs, lows, closes must have the same length")
    if not isinstance(period, int) or period <= 0:
        raise ValueError(f"period must be a positive integer, got {period!r}")

    out = _wilder_atr(h_arr, l_arr, c_arr, period)
    return _wrap(out, is_series, idx)


def adx_series(
    highs: np.ndarray | pd.Series,
    lows: np.ndarray | pd.Series,
    closes: np.ndarray | pd.Series,
    *,
    period: int = 14,
) -> dict[str, np.ndarray | pd.Series]:
    """Average Directional Index as full series (Wilder smoothing).

    Computes +DI, -DI, and ADX for every bar, padding warmup bars with NaN.

    Mathematical definition:
        +DM_t = max(H_t - H_{t-1}, 0)  if H_t - H_{t-1} > L_{t-1} - L_t else 0
        -DM_t = max(L_{t-1} - L_t, 0)  if L_{t-1} - L_t > H_t - H_{t-1} else 0
        TR_t  = max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)

        Wilder-smooth +DM, -DM, TR over `period` bars.
        +DI_t = 100 * sm_plus_t / sm_tr_t
        -DI_t = 100 * sm_minus_t / sm_tr_t
        DX_t  = 100 * |+DI_t - -DI_t| / (+DI_t + -DI_t)
        ADX   = Wilder smooth of DX over `period` bars

    ADX > 25 → trending; ADX < 20 → choppy/ranging.
    Minimum warmup: 2 * period + 1 bars before first valid ADX.

    Parameters
    ----------
    highs, lows, closes : array-like
        OHLC series of equal length (at least 2 * period + 1 bars recommended).
    period : int
        Wilder smoothing period (default 14).

    Returns
    -------
    dict with keys:
        'adx'      : ADX series (0-100)
        'plus_di'  : +DI series (0-100)
        'minus_di' : -DI series (0-100)
    Each same type as closes.

    Raises
    ------
    ValueError
        If arrays have different lengths or period <= 0.

    References
    ----------
    Wilder, J.W. (1978). New Concepts in Technical Trading Systems.
    """
    h_arr, is_series, idx = _to_array(highs)
    l_arr, _, _ = _to_array(lows)
    c_arr, _, _ = _to_array(closes)

    n = len(c_arr)
    if n == 0:
        raise ValueError("Input arrays must not be empty")
    if len(h_arr) != n or len(l_arr) != n:
        raise ValueError("highs, lows, closes must have the same length")
    if not isinstance(period, int) or period <= 0:
        raise ValueError(f"period must be a positive integer, got {period!r}")

    adx_out     = np.full(n, np.nan)
    plus_di_out = np.full(n, np.nan)
    minus_di_out = np.full(n, np.nan)

    if n < 2:
        def _w(a):
            return _wrap(a, is_series, idx)
        return {"adx": _w(adx_out), "plus_di": _w(plus_di_out), "minus_di": _w(minus_di_out)}

    # Compute +DM, -DM, TR for transitions (length n-1)
    plus_dm  = np.zeros(n - 1)
    minus_dm = np.zeros(n - 1)
    trs      = np.zeros(n - 1)
    for i in range(1, n):
        up   = h_arr[i] - h_arr[i - 1]
        down = l_arr[i - 1] - l_arr[i]
        if up > down and up > 0:
            plus_dm[i - 1] = up
        if down > up and down > 0:
            minus_dm[i - 1] = down
        trs[i - 1] = max(
            h_arr[i] - l_arr[i],
            abs(h_arr[i] - c_arr[i - 1]),
            abs(l_arr[i] - c_arr[i - 1]),
        )

    m = len(trs)  # n - 1

    # Wilder smoothing → arrays of length m - period + 1
    def _wilder(values: np.ndarray) -> np.ndarray:
        if len(values) < period:
            return np.full(0, np.nan)
        sm = np.empty(len(values) - period + 1)
        sm[0] = values[:period].sum()
        for i in range(1, len(sm)):
            sm[i] = sm[i - 1] - sm[i - 1] / period + values[period - 1 + i]
        return sm

    sm_tr    = _wilder(trs)
    sm_plus  = _wilder(plus_dm)
    sm_minus = _wilder(minus_dm)

    k = len(sm_tr)  # m - period + 1
    if k == 0:
        def _w(a):
            return _wrap(a, is_series, idx)
        return {"adx": _w(adx_out), "plus_di": _w(plus_di_out), "minus_di": _w(minus_di_out)}

    plus_di_sm  = 100.0 * sm_plus  / np.where(sm_tr > 0, sm_tr, 1.0)
    minus_di_sm = 100.0 * sm_minus / np.where(sm_tr > 0, sm_tr, 1.0)
    di_sum = plus_di_sm + minus_di_sm
    dx_sm  = 100.0 * np.abs(plus_di_sm - minus_di_sm) / np.where(di_sum > 0, di_sum, 1.0)

    # Map smoothed DI back to full array: smoothed index j maps to bar index j + period
    # (+1 for the transition offset)
    di_start = period  # index in original array where first +DI/-DI is valid
    for j in range(k):
        bar_idx = j + period
        if bar_idx < n:
            plus_di_out[bar_idx]  = plus_di_sm[j]
            minus_di_out[bar_idx] = minus_di_sm[j]

    # ADX: Wilder-smooth DX over period more bars
    if k >= period:
        adx_v = np.empty(k - period + 1)
        adx_v[0] = float(dx_sm[:period].mean())
        for i in range(1, len(adx_v)):
            adx_v[i] = (adx_v[i - 1] * (period - 1) + dx_sm[period - 1 + i]) / period
        # ADX index j maps to bar index j + 2*period
        for j in range(len(adx_v)):
            bar_idx = j + 2 * period
            if bar_idx < n:
                adx_out[bar_idx] = adx_v[j]

    def _w(a):
        return _wrap(a, is_series, idx)

    return {"adx": _w(adx_out), "plus_di": _w(plus_di_out), "minus_di": _w(minus_di_out)}


def supertrend(
    highs: np.ndarray | pd.Series,
    lows: np.ndarray | pd.Series,
    closes: np.ndarray | pd.Series,
    *,
    period: int = 10,
    multiplier: float = 3.0,
) -> dict[str, np.ndarray | pd.Series]:
    """SuperTrend indicator.

    Mathematical definition:
        HL2_t    = (H_t + L_t) / 2
        raw_up_t = HL2_t + multiplier * ATR_t
        raw_dn_t = HL2_t - multiplier * ATR_t

        # True bands (prevent band from moving against trend)
        final_up_t = raw_up_t  if raw_up_t < final_up_{t-1} OR C_{t-1} > final_up_{t-1}
                   else final_up_{t-1}
        final_dn_t = raw_dn_t  if raw_dn_t > final_dn_{t-1} OR C_{t-1} < final_dn_{t-1}
                   else final_dn_{t-1}

        direction_t = +1 (uptrend)   if C_t > final_up_{t-1}
                    = -1 (downtrend) if C_t < final_dn_{t-1}
                    = direction_{t-1}  otherwise

        supertrend_line_t = final_dn_t  if direction=+1 (support)
                          = final_up_t  if direction=-1 (resistance)

    Parameters
    ----------
    highs, lows, closes : array-like
        OHLC series of equal length.
    period : int
        ATR lookback period (default 10).
    multiplier : float
        ATR multiplier for band width (default 3.0).

    Returns
    -------
    dict with keys:
        'direction'  : +1 (uptrend) / -1 (downtrend) series
        'upper_band' : upper band (resistance in downtrend)
        'lower_band' : lower band (support in uptrend)
        'line'       : SuperTrend line (active band)
    All same type as closes. NaN for first `period` bars.

    Raises
    ------
    ValueError
        If arrays have different lengths, period <= 0, or multiplier <= 0.

    References
    ----------
    Oliver Seban (2009). SuperTrend indicator concept.
    """
    h_arr, is_series, idx = _to_array(highs)
    l_arr, _, _ = _to_array(lows)
    c_arr, _, _ = _to_array(closes)

    n = len(c_arr)
    if n == 0:
        raise ValueError("Input arrays must not be empty")
    if len(h_arr) != n or len(l_arr) != n:
        raise ValueError("highs, lows, closes must have the same length")
    if not isinstance(period, int) or period <= 0:
        raise ValueError(f"period must be a positive integer, got {period!r}")
    if not (multiplier > 0):
        raise ValueError(f"multiplier must be > 0, got {multiplier!r}")

    atr = _wilder_atr(h_arr, l_arr, c_arr, period)
    hl2 = (h_arr + l_arr) / 2.0

    raw_up = hl2 + multiplier * atr   # NaN where atr is NaN
    raw_dn = hl2 - multiplier * atr

    direction  = np.full(n, np.nan)
    final_up   = np.full(n, np.nan)
    final_dn   = np.full(n, np.nan)
    line       = np.full(n, np.nan)

    # Find first bar with valid ATR
    start = int(np.argmax(~np.isnan(atr)))
    if np.isnan(atr[start]):
        def _w(a):
            return _wrap(a, is_series, idx)
        return {
            "direction": _w(direction), "upper_band": _w(final_up),
            "lower_band": _w(final_dn), "line": _w(line),
        }

    final_up[start]  = raw_up[start]
    final_dn[start]  = raw_dn[start]
    direction[start] = 1.0  # assume uptrend at seed

    for i in range(start + 1, n):
        if np.isnan(raw_up[i]):
            continue

        # True upper band: only tighten (move down)
        if raw_up[i] < final_up[i - 1] or c_arr[i - 1] > final_up[i - 1]:
            final_up[i] = raw_up[i]
        else:
            final_up[i] = final_up[i - 1]

        # True lower band: only tighten (move up)
        if raw_dn[i] > final_dn[i - 1] or c_arr[i - 1] < final_dn[i - 1]:
            final_dn[i] = raw_dn[i]
        else:
            final_dn[i] = final_dn[i - 1]

        # Direction: compare close to the PREVIOUS bar's active band
        if c_arr[i] > final_up[i - 1]:
            direction[i] = 1.0   # breakout above → uptrend
        elif c_arr[i] < final_dn[i - 1]:
            direction[i] = -1.0  # breakdown below → downtrend
        else:
            direction[i] = direction[i - 1]

        # Active line: lower band in uptrend, upper band in downtrend
        if direction[i] == 1.0:
            line[i] = final_dn[i]
        else:
            line[i] = final_up[i]

    def _w(a):
        return _wrap(a, is_series, idx)

    return {
        "direction": _w(direction),
        "upper_band": _w(final_up),
        "lower_band": _w(final_dn),
        "line": _w(line),
    }
