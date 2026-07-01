"""Realized variance from high-frequency returns.

References
----------
Andersen, T.G. & Bollerslev, T. (1998). Answering the Critics: Yes, ARCH
    Models Do Provide Good Volatility Forecasts. International Economic Review,
    39(4), 885-905.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def realized_variance(
    high_freq_returns,
    *,
    sampling_frequency: str = "5min",
    annualize: bool = False,
    periods_per_year: int = 252,
) -> float | np.ndarray:
    """Realized variance from high-frequency returns.

    Realized Variance = sum(r_i^2) for all high-frequency returns in the period.

    For 1-D input: returns a scalar.
    For 2-D input (T x N): returns a T-length array (one RV per row/period).

    Parameters
    ----------
    high_freq_returns : array-like
        1-D: single period's high-frequency returns.
        2-D: T periods x N intraday returns.
    sampling_frequency : str
        Informational only (not used in computation). Default "5min".
    annualize : bool
        If True, multiply by periods_per_year.
    periods_per_year : int
        Trading periods per year (default 252).

    Returns
    -------
    float or np.ndarray
        Realized variance scalar (1-D) or array (2-D).

    Raises
    ------
    ValueError
        If input is empty or has more than 2 dimensions.

    References
    ----------
    Andersen & Bollerslev (1998). International Economic Review, 39(4), 885-905.
    """
    if isinstance(high_freq_returns, pd.DataFrame) or isinstance(high_freq_returns, pd.Series):
        arr = high_freq_returns.to_numpy(dtype=float)
    else:
        arr = np.asarray(high_freq_returns, dtype=float)

    if arr.size == 0:
        raise ValueError("high_freq_returns must not be empty")

    if arr.ndim > 2:
        raise ValueError(f"Expected 1-D or 2-D input, got {arr.ndim}-D")

    if arr.ndim == 1:
        rv = float(np.sum(arr**2))
        if annualize:
            rv *= periods_per_year
        return rv

    # 2-D: sum across columns (N intraday returns) for each row (T periods)
    rv = np.sum(arr**2, axis=1)
    if annualize:
        rv = rv * periods_per_year
    return rv
