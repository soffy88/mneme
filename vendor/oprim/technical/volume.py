"""Volume-based technical indicators: OBV and MFI."""

from __future__ import annotations

import numpy as np
import pandas as pd

from oprim.technical._base import _to_array, _wrap


def obv(
    closes: np.ndarray | pd.Series,
    volumes: np.ndarray | pd.Series,
) -> np.ndarray | pd.Series:
    """On-Balance Volume (OBV).

    Mathematical definition:
        OBV[0] = 0
        OBV[t] = OBV[t-1] + sign(C[t] - C[t-1]) * V[t]
        where sign: +1 if up, -1 if down, 0 if unchanged.

    OBV is a cumulative indicator; its direction matters more than magnitude.

    Parameters
    ----------
    closes : array-like
        Close prices.
    volumes : array-like
        Trading volumes (same length as closes).

    Returns
    -------
    Same type as closes, starting at 0.

    Raises
    ------
    ValueError
        If arrays have different lengths or are empty.

    References
    ----------
    Granville, J.E. (1963). Granville's New Key to Stock Market Profits.
    """
    c_arr, is_series, idx = _to_array(closes)
    v_arr, _, _ = _to_array(volumes)

    n = len(c_arr)
    if n == 0:
        raise ValueError("closes must not be empty")
    if len(v_arr) != n:
        raise ValueError(f"closes and volumes must have same length: {n} vs {len(v_arr)}")

    out = np.zeros(n)
    for t in range(1, n):
        diff = c_arr[t] - c_arr[t - 1]
        if diff > 0:
            out[t] = out[t - 1] + v_arr[t]
        elif diff < 0:
            out[t] = out[t - 1] - v_arr[t]
        else:
            out[t] = out[t - 1]

    return _wrap(out, is_series, idx)


def mfi(
    highs: np.ndarray | pd.Series,
    lows: np.ndarray | pd.Series,
    closes: np.ndarray | pd.Series,
    volumes: np.ndarray | pd.Series,
    *,
    period: int = 14,
    normalize: bool = True,
) -> np.ndarray | pd.Series:
    """Money Flow Index (MFI).

    Mathematical definition:
        TP_t = (H_t + L_t + C_t) / 3
        money_flow_t = TP_t * V_t
        positive_mf: when TP_t > TP_{t-1}
        negative_mf: when TP_t < TP_{t-1}
        MFR = sum(positive_mf, period) / sum(negative_mf, period)
        MFI = 100 - 100/(1+MFR)          [if normalize=False]
        MFI = 1 - 1/(1+MFR)             [if normalize=True, in [0,1]]

    When negative_mf = 0 (pure buying pressure): MFI = 100 or 1.0.

    Parameters
    ----------
    highs, lows, closes, volumes : array-like
        OHLC and volume series of equal length.
    period : int
        Rolling lookback period. Default 14.
    normalize : bool
        If True, return values in [0, 1]. If False, in [0, 100].

    Returns
    -------
    Same type as closes, NaN for first period positions.

    Raises
    ------
    ValueError
        If arrays have different lengths or period is invalid.

    References
    ----------
    Quong, G. & Soudack, A. (1989). Price-Volume Trend. Stocks & Commodities.
    """
    h_arr, is_series, idx = _to_array(highs)
    l_arr, _, _ = _to_array(lows)
    c_arr, _, _ = _to_array(closes)
    v_arr, _, _ = _to_array(volumes)

    n = len(c_arr)
    if n == 0:
        raise ValueError("Input arrays must not be empty")
    for name, arr in [("highs", h_arr), ("lows", l_arr), ("volumes", v_arr)]:
        if len(arr) != n:
            raise ValueError(f"closes and {name} must have same length")
    if not isinstance(period, int) or period <= 0:
        raise ValueError(f"period must be a positive integer, got {period!r}")

    # Typical price and money flow
    tp = (h_arr + l_arr + c_arr) / 3.0
    money_flow = tp * v_arr

    out = np.full(n, np.nan)

    for i in range(period, n):
        # Slice of period bars ending at i
        tp_window = tp[i - period : i + 1]     # length period+1
        mf_window = money_flow[i - period : i + 1]  # length period+1

        pos_mf = 0.0
        neg_mf = 0.0
        for j in range(1, period + 1):
            if tp_window[j] > tp_window[j - 1]:
                pos_mf += mf_window[j]
            elif tp_window[j] < tp_window[j - 1]:
                neg_mf += mf_window[j]

        if neg_mf == 0:
            mfi_val = 1.0 if normalize else 100.0
        else:
            mfr = pos_mf / neg_mf
            if normalize:
                mfi_val = 1.0 - 1.0 / (1.0 + mfr)
            else:
                mfi_val = 100.0 - 100.0 / (1.0 + mfr)

        out[i] = mfi_val

    return _wrap(out, is_series, idx)
