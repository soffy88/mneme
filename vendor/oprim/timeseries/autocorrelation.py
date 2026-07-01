"""Autocorrelation tests: Ljung-Box and Durbin-Watson.

References
----------
Ljung, G.M. & Box, G.E.P. (1978). On a measure of lack of fit in time series
    models. Biometrika, 65(2), 297-303.
Durbin, J. & Watson, G.S. (1950). Testing for Serial Correlation in Least
    Squares Regression: I. Biometrika, 37(3/4), 409-428.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def ljung_box_test(
    residuals: np.ndarray | pd.Series,
    *,
    lags: int | list[int] = 10,
    boxpierce: bool = False,
) -> dict:
    """Ljung-Box (or Box-Pierce) portmanteau test for autocorrelation.

    H0: No autocorrelation in residuals up to the specified lag.

    Q_LB = n*(n+2) * sum(rho_k^2 / (n-k), k=1..h)
    p-value from chi2 distribution with h degrees of freedom.

    Parameters
    ----------
    residuals : array-like
        Model residuals or time series.
    lags : int or list of int
        Maximum lag (int) or specific lags to test (list).
    boxpierce : bool
        If True, compute Box-Pierce statistic instead:
        Q_BP = n * sum(rho_k^2, k=1..h).

    Returns
    -------
    dict with keys:
        statistics, p_values, lags_tested, n_obs

    Raises
    ------
    ValueError
        If residuals is empty or lags is invalid.

    References
    ----------
    Ljung & Box (1978). Biometrika, 65(2), 297-303.
    """
    if isinstance(residuals, pd.Series):
        arr = residuals.dropna().to_numpy(dtype=float)
    else:
        arr = np.asarray(residuals, dtype=float)

    n = len(arr)
    if n == 0:
        raise ValueError("residuals must not be empty")

    # Normalize lags to a list
    if isinstance(lags, int):
        if lags <= 0:
            raise ValueError(f"lags must be positive, got {lags}")
        lags_list = list(range(1, lags + 1))
    else:
        lags_list = list(lags)
        if any(lag <= 0 for lag in lags_list):
            raise ValueError("all lags must be positive")

    # Compute autocorrelations
    arr_demeaned = arr - np.mean(arr)
    var = np.sum(arr_demeaned**2)

    def _acf(k):
        """Sample autocorrelation at lag k."""
        if k >= n or var == 0:
            return 0.0
        return float(np.sum(arr_demeaned[k:] * arr_demeaned[:-k]) / var)

    # Compute all needed autocorrelations up to max lag
    max_lag = max(lags_list)
    acfs = [_acf(k) for k in range(1, max_lag + 1)]

    statistics = []
    p_values = []

    for h in lags_list:
        if boxpierce:
            q = float(n * np.sum(np.array(acfs[:h]) ** 2))
        else:
            q = float(n * (n + 2) * np.sum(
                [acfs[k - 1] ** 2 / (n - k) for k in range(1, h + 1)]
            ))
        p_val = float(stats.chi2.sf(q, df=h))
        statistics.append(q)
        p_values.append(p_val)

    if isinstance(lags, int):
        # Return summary for the maximum lag
        return {
            "statistic": statistics[-1],
            "p_value": p_values[-1],
            "statistics": statistics,
            "p_values": p_values,
            "lags_tested": lags_list,
            "n_obs": int(n),
        }
    return {
        "statistics": statistics,
        "p_values": p_values,
        "lags_tested": lags_list,
        "n_obs": int(n),
    }


def durbin_watson(residuals: np.ndarray | pd.Series) -> float:
    """Durbin-Watson statistic for first-order serial correlation.

    DW = sum((e_t - e_{t-1})^2) / sum(e_t^2)

    Values near 2 indicate no autocorrelation.
    Values < 2 indicate positive autocorrelation.
    Values > 2 indicate negative autocorrelation.

    Parameters
    ----------
    residuals : array-like
        OLS residuals.

    Returns
    -------
    float
        Durbin-Watson statistic in [0, 4].

    Raises
    ------
    ValueError
        If fewer than 2 residuals.

    References
    ----------
    Durbin & Watson (1950). Biometrika, 37(3/4), 409-428.
    """
    if isinstance(residuals, pd.Series):
        arr = residuals.dropna().to_numpy(dtype=float)
    else:
        arr = np.asarray(residuals, dtype=float)

    if len(arr) < 2:
        raise ValueError(f"Need at least 2 residuals, got {len(arr)}")

    diff_sq = float(np.sum(np.diff(arr) ** 2))
    sq_sum = float(np.sum(arr**2))

    if sq_sum == 0:
        return 2.0  # degenerate case

    return float(diff_sq / sq_sum)
