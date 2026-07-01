"""Granger causality test.

References
----------
Granger, C.W.J. (1969). Investigating Causal Relations by Econometric Models
    and Cross-spectral Methods. Econometrica, 37(3), 424-438.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from oprim.timeseries._base import _ols_fit


def granger_causality_test(
    y: np.ndarray | pd.Series,
    x: np.ndarray | pd.Series,
    *,
    max_lag: int = 4,
    test: str = "F",
) -> dict:
    """Granger causality test: does x Granger-cause y?

    H0: x does NOT Granger-cause y (lags of x have no predictive power for y).

    Restricted model:  y_t = a0 + a1*y_{t-1} + ... + a_p*y_{t-p} + eps
    Unrestricted model: y_t = a0 + a1*y_{t-1} + ... + b1*x_{t-1} + ... + eps

    F = ((SSR_R - SSR_U) / max_lag) / (SSR_U / (n - 2*max_lag - 1))
    p-value from scipy.stats.f.sf(F, max_lag, n - 2*max_lag - 1)

    Parameters
    ----------
    y : array-like
        Dependent variable (potentially caused).
    x : array-like
        Candidate cause variable.
    max_lag : int
        Number of lags for both y and x. Default 4.
    test : {"F", "chi2"}
        Test statistic type. Default "F".

    Returns
    -------
    dict with keys:
        f_statistic (or chi2_statistic), p_value, max_lag, n_obs,
        ssr_restricted, ssr_unrestricted, df_num, df_denom,
        granger_causes (bool: reject H0 at 5%)

    Raises
    ------
    ValueError
        If lengths differ, max_lag invalid, or too few observations.

    References
    ----------
    Granger, C.W.J. (1969). Econometrica, 37(3), 424-438.
    """
    if isinstance(y, pd.Series):
        y_arr = y.dropna().to_numpy(dtype=float)
    else:
        y_arr = np.asarray(y, dtype=float)
    if isinstance(x, pd.Series):
        x_arr = x.dropna().to_numpy(dtype=float)
    else:
        x_arr = np.asarray(x, dtype=float)

    if len(y_arr) != len(x_arr):
        raise ValueError(f"y and x must have same length: {len(y_arr)} vs {len(x_arr)}")
    n_total = len(y_arr)
    if max_lag <= 0:
        raise ValueError(f"max_lag must be positive, got {max_lag}")
    if n_total < 2 * max_lag + 10:
        raise ValueError(
            f"Need at least {2*max_lag+10} observations, got {n_total}"
        )

    # Build matrices for regression starting at index max_lag
    n_eff = n_total - max_lag  # effective sample size

    # Dependent: y[max_lag:]
    endog = y_arr[max_lag:]

    # Restricted model: const + y_{t-1..max_lag}
    cols_r = [np.ones(n_eff)]
    for lag in range(1, max_lag + 1):
        cols_r.append(y_arr[max_lag - lag : n_total - lag])
    X_r = np.column_stack(cols_r)

    # Unrestricted model: add x_{t-1..max_lag}
    cols_u = list(cols_r)
    for lag in range(1, max_lag + 1):
        cols_u.append(x_arr[max_lag - lag : n_total - lag])
    X_u = np.column_stack(cols_u)

    # OLS fits
    _, resid_r = _ols_fit(endog, X_r)
    _, resid_u = _ols_fit(endog, X_u)

    ssr_r = float(np.sum(resid_r**2))
    ssr_u = float(np.sum(resid_u**2))

    df_num = max_lag
    df_denom = n_eff - 2 * max_lag - 1

    if df_denom <= 0:
        raise ValueError("Too few degrees of freedom in unrestricted model")
    if ssr_u <= 0:
        f_stat = 0.0
    else:
        f_stat = float(((ssr_r - ssr_u) / df_num) / (ssr_u / df_denom))

    f_stat = max(f_stat, 0.0)
    p_value = float(stats.f.sf(f_stat, df_num, df_denom))

    if test == "chi2":
        chi2_stat = float(f_stat * df_num)
        p_value_chi2 = float(stats.chi2.sf(chi2_stat, df=df_num))
        return {
            "chi2_statistic": chi2_stat,
            "f_statistic": f_stat,
            "p_value": p_value_chi2,
            "max_lag": int(max_lag),
            "n_obs": int(n_eff),
            "ssr_restricted": ssr_r,
            "ssr_unrestricted": ssr_u,
            "df_num": int(df_num),
            "df_denom": int(df_denom),
            "granger_causes": bool(p_value_chi2 < 0.05),
        }

    return {
        "f_statistic": float(f_stat),
        "p_value": float(p_value),
        "max_lag": int(max_lag),
        "n_obs": int(n_eff),
        "ssr_restricted": float(ssr_r),
        "ssr_unrestricted": float(ssr_u),
        "df_num": int(df_num),
        "df_denom": int(df_denom),
        "granger_causes": bool(p_value < 0.05),
    }
