"""Range-based volatility estimators: Parkinson, Garman-Klass, Yang-Zhang.

References
----------
Parkinson, M. (1980). The Extreme Value Method for Estimating the Variance of
    the Rate of Return. Journal of Business, 53(1), 61-65.
Garman, M.B. & Klass, M.J. (1980). On the Estimation of Security Price
    Volatilities from Historical Data. Journal of Business, 53(1), 67-78.
Yang, D. & Zhang, Q. (2000). Drift-Independent Volatility Estimation Based on
    High, Low, Open, and Close Prices. Journal of Business, 73(3), 477-491.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _to_array(x) -> np.ndarray:
    """Convert to float64 numpy array."""
    if isinstance(x, pd.Series):
        return x.to_numpy(dtype=float)
    return np.asarray(x, dtype=float)


def parkinson_volatility(
    highs,
    lows,
    *,
    annualize: bool = False,
    periods_per_year: int = 252,
) -> float:
    """Parkinson (extreme value) volatility estimator.

    sigma^2 = (1 / (4*ln(2))) * mean(ln(H_t/L_t)^2)

    More efficient than close-to-close for diffusion processes.
    Does NOT capture overnight gaps or drift.

    Parameters
    ----------
    highs, lows : array-like
        Per-bar high and low prices.
    annualize : bool
        If True, annualize: sigma_daily * sqrt(periods_per_year).
    periods_per_year : int
        Default 252.

    Returns
    -------
    float
        Annualized or daily volatility estimate (sigma, not variance).

    Raises
    ------
    ValueError
        If arrays have different lengths or are empty.

    References
    ----------
    Parkinson (1980). Journal of Business, 53(1), 61-65.
    """
    h = _to_array(highs)
    l = _to_array(lows)

    if len(h) == 0 or len(l) == 0:
        raise ValueError("highs and lows must not be empty")
    if len(h) != len(l):
        raise ValueError(f"highs and lows must have same length: {len(h)} vs {len(l)}")
    if np.any(h < l):
        raise ValueError("highs must be >= lows for all bars")

    hl_ratio = np.log(h / l)
    var = np.mean(hl_ratio**2) / (4.0 * np.log(2.0))
    sigma = float(np.sqrt(max(var, 0.0)))

    if annualize:
        sigma *= np.sqrt(float(periods_per_year))
    return sigma


def garman_klass_volatility(
    opens,
    highs,
    lows,
    closes,
    *,
    annualize: bool = False,
    periods_per_year: int = 252,
) -> float:
    """Garman-Klass volatility estimator.

    sigma^2 = mean(0.5*ln(H/L)^2 - (2*ln(2) - 1)*ln(C/O)^2)

    More efficient than Parkinson; uses open-close range to capture drift.

    Parameters
    ----------
    opens, highs, lows, closes : array-like
        OHLC price series of equal length.
    annualize : bool
        If True, return annualized volatility.
    periods_per_year : int
        Default 252.

    Returns
    -------
    float
        Volatility estimate (sigma).

    Raises
    ------
    ValueError
        If arrays have different lengths or are empty.

    References
    ----------
    Garman & Klass (1980). Journal of Business, 53(1), 67-78.
    """
    o = _to_array(opens)
    h = _to_array(highs)
    l = _to_array(lows)
    c = _to_array(closes)

    n = len(o)
    if n == 0:
        raise ValueError("Input arrays must not be empty")
    for name, arr in [("highs", h), ("lows", l), ("closes", c)]:
        if len(arr) != n:
            raise ValueError(f"opens and {name} must have same length: {n} vs {len(arr)}")

    log_hl = np.log(h / l)
    log_co = np.log(c / o)

    var = np.mean(0.5 * log_hl**2 - (2.0 * np.log(2.0) - 1.0) * log_co**2)
    var = max(float(var), 0.0)
    sigma = float(np.sqrt(var))

    if annualize:
        sigma *= np.sqrt(float(periods_per_year))
    return sigma


def yang_zhang_volatility(
    opens,
    highs,
    lows,
    closes,
    *,
    window: int = 20,
    annualize: bool = False,
    periods_per_year: int = 252,
) -> np.ndarray:
    """Yang-Zhang drift-independent volatility estimator.

    Combines overnight, open-to-close, and Rogers-Satchell components.

    sigma_oc^2  = var(ln(O_t / C_{t-1}), ddof=1)   [overnight]
    sigma_co^2  = var(ln(C_t / O_t), ddof=1)        [open-to-close]
    sigma_rs^2  = mean(ln(H/O)*ln(H/C) + ln(L/O)*ln(L/C))  [Rogers-Satchell]
    k           = 0.34 / (1.34 + (window+1)/(window-1))
    sigma_YZ^2  = sigma_oc^2 + k*sigma_co^2 + (1-k)*sigma_rs^2

    Parameters
    ----------
    opens, highs, lows, closes : array-like
        OHLC price series of equal length (at least window+1 bars).
    window : int
        Rolling window size. Default 20.
    annualize : bool
        If True, return annualized volatility.
    periods_per_year : int
        Default 252.

    Returns
    -------
    np.ndarray
        Volatility estimates, NaN-padded for first (window) positions.
        Length equals n_bars.

    Raises
    ------
    ValueError
        If arrays have different lengths or window is invalid.

    References
    ----------
    Yang & Zhang (2000). Journal of Business, 73(3), 477-491.
    """
    o = _to_array(opens)
    h = _to_array(highs)
    l = _to_array(lows)
    c = _to_array(closes)

    n = len(o)
    if n == 0:
        raise ValueError("Input arrays must not be empty")
    for name, arr in [("highs", h), ("lows", l), ("closes", c)]:
        if len(arr) != n:
            raise ValueError(f"opens and {name} must have same length: {n} vs {len(arr)}")

    if not isinstance(window, int) or window < 2:
        raise ValueError(f"window must be an integer >= 2, got {window!r}")

    # Log return components
    log_oc = np.log(o[1:] / c[:-1])    # overnight: O_t / C_{t-1}, length n-1
    log_co = np.log(c[1:] / o[1:])     # open-to-close: C_t / O_t, length n-1
    # Rogers-Satchell for each bar (from index 1 onwards)
    log_ho = np.log(h[1:] / o[1:])
    log_hc = np.log(h[1:] / c[1:])
    log_lo = np.log(l[1:] / o[1:])
    log_lc = np.log(l[1:] / c[1:])
    rs = log_ho * log_hc + log_lo * log_lc  # length n-1

    k = 0.34 / (1.34 + (window + 1.0) / (window - 1.0))

    out = np.full(n, np.nan)

    for i in range(window, n):
        # Slice of length window from log_oc, log_co, rs (0-indexed as i-window..i-1)
        oc_slice = log_oc[i - window : i]
        co_slice = log_co[i - window : i]
        rs_slice = rs[i - window : i]

        var_oc = float(np.var(oc_slice, ddof=1)) if window > 1 else 0.0
        var_co = float(np.var(co_slice, ddof=1)) if window > 1 else 0.0
        var_rs = float(np.mean(rs_slice))

        yz_var = var_oc + k * var_co + (1.0 - k) * var_rs
        yz_var = max(yz_var, 0.0)
        sigma = float(np.sqrt(yz_var))

        if annualize:
            sigma *= np.sqrt(float(periods_per_year))
        out[i] = sigma

    return out
