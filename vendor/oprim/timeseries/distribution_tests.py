"""Distribution normality tests: Jarque-Bera.

References
----------
Jarque, C.M. & Bera, A.K. (1987). A test for normality of observations and
    regression residuals. International Statistical Review, 55(2), 163-172.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def jarque_bera_test(data: np.ndarray | pd.Series) -> dict:
    """Jarque-Bera test for normality.

    H0: the data is normally distributed (skewness=0, excess kurtosis=0).

    JB = (n/6) * (S^2 + (K-3)^2/4)
    p-value from chi2 distribution with 2 degrees of freedom.

    Parameters
    ----------
    data : array-like
        Sample data.

    Returns
    -------
    dict with keys:
        statistic, p_value, skewness, kurtosis (raw 4th moment / sigma^4),
        excess_kurtosis (kurtosis - 3), is_normal (fail to reject at 5%)

    Raises
    ------
    ValueError
        If data has fewer than 8 observations.

    References
    ----------
    Jarque & Bera (1987). International Statistical Review, 55(2), 163-172.
    """
    if isinstance(data, pd.Series):
        arr = data.dropna().to_numpy(dtype=float)
    else:
        arr = np.asarray(data, dtype=float)

    n = len(arr)
    if n < 8:
        raise ValueError(f"Need at least 8 observations for Jarque-Bera test, got {n}")

    mean = np.mean(arr)
    std = np.std(arr, ddof=0)

    if std == 0:
        # Degenerate: constant series
        return {
            "statistic": 0.0,
            "p_value": 1.0,
            "skewness": 0.0,
            "kurtosis": 0.0,
            "excess_kurtosis": -3.0,
            "is_normal": True,
        }

    # Standardized moments
    z = (arr - mean) / std
    S = float(np.mean(z**3))   # skewness
    K = float(np.mean(z**4))   # raw kurtosis (=3 for normal)
    excess_K = K - 3.0

    jb = float(n / 6.0 * (S**2 + excess_K**2 / 4.0))
    p_value = float(stats.chi2.sf(jb, df=2))
    is_normal = bool(p_value >= 0.05)

    return {
        "statistic": jb,
        "p_value": p_value,
        "skewness": S,
        "kurtosis": K,
        "excess_kurtosis": excess_K,
        "is_normal": is_normal,
    }
