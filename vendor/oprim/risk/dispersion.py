"""Dispersion measures: Mean Deviation."""

from __future__ import annotations

import numpy as np
import pandas as pd


def mean_deviation(
    series: np.ndarray | pd.Series,
    *,
    window: int | None = None,
    center: str = "mean",
) -> float | np.ndarray | pd.Series:
    """Mean absolute deviation from the specified center measure.

    Mathematical definition:
        MD = mean(|x_i - center(x)|)

    Scalar (window=None): collapses entire series to a single float.
    Rolling (window=int): for each position i, computes over series[i-window+1:i+1];
        first (window-1) positions are NaN.

    Parameters
    ----------
    series : array-like
        Numeric series.
    window : int or None
        Rolling window size. None returns scalar.
    center : {"mean", "median"}
        Center measure. "mean" uses np.mean; "median" uses np.median.

    Returns
    -------
    float | np.ndarray | pd.Series
        Scalar when window=None; array/Series (same type as input) for rolling.

    Raises
    ------
    ValueError
        If series is empty, window <= 0, or center is not "mean"/"median".
    """
    if center not in ("mean", "median"):
        raise ValueError(f"center must be 'mean' or 'median', got {center!r}")

    is_series = isinstance(series, pd.Series)
    idx = series.index if is_series else None
    arr = np.asarray(series, dtype=float)

    if arr.ndim != 1 or len(arr) == 0:
        raise ValueError("series must be a non-empty 1-D array")

    center_fn = np.mean if center == "mean" else np.median

    if window is None:
        c = center_fn(arr)
        return float(np.mean(np.abs(arr - c)))

    if not isinstance(window, int) or window <= 0:
        raise ValueError(f"window must be a positive integer, got {window!r}")

    n = len(arr)
    out = np.full(n, np.nan)
    for i in range(window - 1, n):
        sub = arr[i - window + 1 : i + 1]
        c = center_fn(sub)
        out[i] = float(np.mean(np.abs(sub - c)))

    if is_series:
        return pd.Series(out, index=idx)
    return out
