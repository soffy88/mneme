"""Exponentially Weighted Moving Average (EWMA) volatility.

Reference: JP Morgan RiskMetrics Technical Document (1996).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ewma_volatility(
    returns,
    *,
    lambda_: float = 0.94,
    initial_variance=None,
    annualize: bool = False,
    periods_per_year: int = 252,
):
    """Compute EWMA volatility (RiskMetrics model).

    Recursion: sigma_t^2 = lambda_ * sigma_{t-1}^2 + (1 - lambda_) * r_{t-1}^2

    Parameters
    ----------
    returns : array-like or pd.Series
        Return series.
    lambda_ : float, optional
        Decay factor in (0, 1) exclusive. Default 0.94.
    initial_variance : float or None, optional
        Seed variance. If None, uses var(returns).
    annualize : bool, optional
        If True, multiply output by sqrt(periods_per_year).
    periods_per_year : int, optional
        Used only when annualize=True. Default 252.

    Returns
    -------
    np.ndarray or pd.Series
        Conditional volatility (std dev), same type as input.

    Raises
    ------
    ValueError
        If lambda_ not in (0, 1) exclusive.

    References
    ----------
    JP Morgan (1996). RiskMetrics Technical Document, 4th ed.
    """
    if lambda_ <= 0 or lambda_ >= 1:
        raise ValueError(f"lambda_ must be in (0, 1) exclusive, got {lambda_}")

    is_series = isinstance(returns, pd.Series)
    if is_series:
        index = returns.index
        arr = returns.to_numpy(dtype=float)
    else:
        arr = np.asarray(returns, dtype=float)

    n = len(arr)
    sigma2 = np.zeros(n)

    if initial_variance is None:
        seed = float(np.var(arr))
    else:
        seed = float(initial_variance)

    # sigma2[t] is the variance estimate at time t (before observing r_t)
    # i.e., sigma_1^2 = lambda_*sigma_0^2 + (1-lambda_)*r_0^2
    sigma2[0] = lambda_ * seed + (1.0 - lambda_) * arr[0] ** 2
    for t in range(1, n):
        sigma2[t] = lambda_ * sigma2[t - 1] + (1.0 - lambda_) * arr[t - 1] ** 2

    result = np.sqrt(sigma2)

    if annualize:
        result = result * np.sqrt(periods_per_year)

    if is_series:
        return pd.Series(result, index=index)
    return result
