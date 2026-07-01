"""Cumulative returns computation.

Reference: Standard finance textbook definition.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def cumulative_returns(
    returns,
    *,
    starting_value: float = 1.0,
    method: str = "simple",
):
    """Compute cumulative returns from a return series.

    Parameters
    ----------
    returns : array-like or pd.Series
        Period return series (e.g., 0.01 for 1%).
    starting_value : float, optional
        Initial portfolio value. Must be > 0. Default 1.0.
    method : {"simple", "log"}, optional
        Compounding method. Default "simple".

    Returns
    -------
    np.ndarray or pd.Series
        Cumulative returns, same type as input.

    Raises
    ------
    ValueError
        If starting_value <= 0 or method is unknown.
    """
    if starting_value <= 0:
        raise ValueError(f"starting_value must be > 0, got {starting_value}")

    is_series = isinstance(returns, pd.Series)
    if is_series:
        index = returns.index
        arr = returns.to_numpy(dtype=float)
    else:
        arr = np.asarray(returns, dtype=float)

    if method == "simple":
        result = starting_value * np.cumprod(1.0 + arr)
    elif method == "log":
        result = starting_value * np.exp(np.cumsum(arr))
    else:
        raise ValueError(f"Unknown method '{method}'. Expected 'simple' or 'log'.")

    if is_series:
        return pd.Series(result, index=index)
    return result
