"""Signal processing atomic operations."""

from __future__ import annotations

import numpy as np


def linear_slope(
    values: np.ndarray,
    normalize: bool = True,
) -> float:
    """Absolute linear regression slope over a window.

    Parameters
    ----------
    values : np.ndarray
        1-D array of values (e.g., prices or features).
    normalize : bool
        If True, divide slope by mean(values) for dimensionless rate.

    Returns
    -------
    float
        Slope (or normalized slope if normalize=True).

    References
    ----------
    .. [1] Extraction source: Selene project, sel_engine/features/price.py:compute_price_slope_6h
    """
    if len(values) < 2:
        raise ValueError("Need at least 2 values for slope")
    x = np.arange(len(values), dtype=float)
    slope = float(np.polyfit(x, values, 1)[0])
    if normalize:
        mean_val = float(np.mean(values))
        if mean_val == 0.0:
            return 0.0
        return abs(slope) / mean_val
    return slope


def atr(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> float:
    """Average True Range with Wilder smoothing.

    Parameters
    ----------
    highs, lows, closes : np.ndarray
        OHLC arrays (same length, at least period+1 bars).
    period : int
        Smoothing period (default 14).

    Returns
    -------
    float
        Current ATR value.

    References
    ----------
    .. [1] Wilder, J.W. (1978). New Concepts in Technical Trading Systems.
    .. [2] Extraction source: Selene project, services/signal/regime/detector.py:_calc_atr
    """
    n = len(closes)
    if n < period + 1:
        raise ValueError(f"Need at least {period+1} bars, got {n}")
    trs = np.empty(n - 1)
    for i in range(1, n):
        trs[i - 1] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    # Wilder smoothing: SMA seed then recursive
    atr_val = float(trs[:period].mean())
    for tr in trs[period:]:
        atr_val = (atr_val * (period - 1) + tr) / period
    return atr_val


def hurst_exponent(
    series: np.ndarray,
    min_window: int = 10,
) -> float:
    """Hurst exponent via rescaled range (R/S) analysis.

    H > 0.5: trending (persistent)
    H = 0.5: random walk
    H < 0.5: mean-reverting (anti-persistent)

    Parameters
    ----------
    series : np.ndarray
        1-D time series (prices or returns).
    min_window : int
        Minimum sub-window size for R/S computation.

    Returns
    -------
    float
        Estimated Hurst exponent.

    References
    ----------
    .. [1] Hurst, H.E. (1951). Long-term storage capacity of reservoirs.
    .. [2] Extraction source: Selene project, sel_engine/features/derived.py:compute_hurst_rs
    """
    n = len(series)
    if n < min_window * 2:
        raise ValueError(f"Series too short: {n} < {min_window * 2}")

    # Generate window sizes (powers of 2 that fit)
    max_k = int(np.log2(n))
    sizes = [int(2**i) for i in range(int(np.log2(min_window)), max_k + 1) if 2**i <= n // 2]
    if len(sizes) < 2:
        raise ValueError("Not enough window sizes for regression")

    rs_means = []
    for size in sizes:
        n_chunks = n // size
        rs_vals = []
        for i in range(n_chunks):
            chunk = series[i * size: (i + 1) * size]
            mean_c = chunk.mean()
            deviations = np.cumsum(chunk - mean_c)
            R = deviations.max() - deviations.min()
            S = chunk.std(ddof=1)
            if S > 0:
                rs_vals.append(R / S)
        if rs_vals:
            rs_means.append(np.mean(rs_vals))
        else:
            rs_means.append(np.nan)

    # Log-log regression
    valid = [(s, r) for s, r in zip(sizes, rs_means) if np.isfinite(r) and r > 0]
    if len(valid) < 2:
        return 0.5  # fallback
    log_sizes = np.log([v[0] for v in valid])
    log_rs = np.log([v[1] for v in valid])
    H = float(np.polyfit(log_sizes, log_rs, 1)[0])
    return max(0.0, min(1.0, H))


def compute_dwt(  # pragma: no cover
    returns: np.ndarray,
    wavelet: str = "db4",
    level: int = 6,
) -> dict[str, np.ndarray | list[float]]:
    """Discrete Wavelet Transform decomposition with energy distribution.

    Parameters
    ----------
    returns : np.ndarray
        1-D array of returns.
    wavelet : str
        Wavelet family (default "db4").
    level : int
        Decomposition level.

    Returns
    -------
    dict
        Keys: "coeffs" (list of arrays), "energy_pct" (list of floats per level),
        "dominant_level" (int).

    References
    ----------
    .. [1] Mallat, S. (2009). A Wavelet Tour of Signal Processing.
    .. [2] Extraction source: Selene project, sel_v2/offline/wavelet.py:compute_dwt
    """
    import pywt

    min_len = pywt.dwt_max_level(len(returns), wavelet)
    actual_level = min(level, min_len)
    if actual_level < 1:
        raise ValueError(f"Series too short for DWT: len={len(returns)}")

    coeffs = pywt.wavedec(returns, wavelet, level=actual_level, mode="periodization")
    # Energy per level
    energies = [float(np.sum(c**2)) for c in coeffs]
    total_energy = sum(energies)
    energy_pct = [e / total_energy if total_energy > 0 else 0.0 for e in energies]
    # Level 0 = approximation, 1..N = detail (coarse to fine)
    dominant_level = int(np.argmax(energy_pct[1:])) + 1 if len(energy_pct) > 1 else 0

    return {
        "coeffs": coeffs,
        "energy_pct": energy_pct,
        "dominant_level": dominant_level,
    }


def H_change_rate_std(
    values: np.ndarray,
    window: int = 6,
) -> float:
    """Standard deviation of first-differences over a window.

    Measures the volatility of a feature's rate of change.

    Parameters
    ----------
    values : np.ndarray
        1-D array (at least window+1 elements).
    window : int
        Number of bars for the computation.

    Returns
    -------
    float
        Std of first-differences.

    References
    ----------
    .. [1] Extraction source: Selene project, sel_engine/features/liquidity.py:compute_H_change_rate_std
    """
    if len(values) < window + 1:
        raise ValueError(f"Need at least {window+1} values, got {len(values)}")
    segment = values[-(window + 1):]
    diffs = np.diff(segment)
    return float(np.std(diffs, ddof=1))


def orderbook_entropy(
    sizes: np.ndarray,
) -> float:
    """Shannon entropy of orderbook level sizes (concentration measure).

    High entropy = evenly distributed liquidity.
    Low entropy = concentrated at few levels.

    Parameters
    ----------
    sizes : np.ndarray
        Array of order sizes at each level (must be positive).

    Returns
    -------
    float
        Shannon entropy in nats.

    References
    ----------
    .. [1] Shannon, C.E. (1948). A Mathematical Theory of Communication.
    .. [2] Extraction source: Selene project, sel_engine/features/liquidity.py:compute_orderbook_entropy
    """
    sizes = np.asarray(sizes, dtype=float)
    sizes = sizes[sizes > 0]
    if len(sizes) == 0:
        return 0.0
    total = sizes.sum()
    if total <= 0:  # pragma: no cover
        return 0.0  # pragma: no cover
    probs = sizes / total
    return float(-np.sum(probs * np.log(probs)))
