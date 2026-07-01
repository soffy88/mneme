"""Heteroskedasticity tests: Breusch-Pagan.

References
----------
Breusch, T.S. & Pagan, A.R. (1979). A Simple Test for Heteroscedasticity and
    Random Coefficient Variation. Econometrica, 47(5), 1287-1294.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from oprim.timeseries._base import _ols_fit


def breusch_pagan_test(
    residuals: np.ndarray | pd.Series,
    exog: np.ndarray | pd.DataFrame,
) -> dict:
    """Breusch-Pagan test for heteroskedasticity.

    H0: homoskedasticity (variance of residuals is constant).

    Procedure:
    1. Regress squared residuals on exog (with added constant).
    2. LM = n * R^2 from that auxiliary regression.
    3. p-value from chi2 distribution with (k-1) degrees of freedom.

    Parameters
    ----------
    residuals : array-like
        OLS residuals from the primary regression.
    exog : array-like, shape (n, k) or (n,)
        Exogenous variables (regressors from primary model).
        Do NOT include a constant — it is added automatically.

    Returns
    -------
    dict with keys:
        lm_statistic, lm_p_value, f_statistic, f_p_value,
        r_squared_aux, df, n_obs, is_homoskedastic

    Raises
    ------
    ValueError
        If lengths mismatch or too few observations.

    References
    ----------
    Breusch & Pagan (1979). Econometrica, 47(5), 1287-1294.
    """
    if isinstance(residuals, pd.Series):
        e = residuals.dropna().to_numpy(dtype=float)
    else:
        e = np.asarray(residuals, dtype=float)

    if isinstance(exog, pd.DataFrame):
        X = exog.to_numpy(dtype=float)
    else:
        X = np.asarray(exog, dtype=float)

    if X.ndim == 1:
        X = X.reshape(-1, 1)

    n = len(e)
    if X.shape[0] != n:
        raise ValueError(f"residuals and exog must have same length: {n} vs {X.shape[0]}")
    if n < 10:
        raise ValueError(f"Need at least 10 observations, got {n}")

    # Dependent: squared residuals
    e2 = e**2

    # Add constant to exog
    X_aug = np.column_stack([np.ones(n), X])
    k = X_aug.shape[1]  # includes constant

    # OLS: e^2 on X_aug
    coeffs, resid_aux = _ols_fit(e2, X_aug)

    # R^2 of auxiliary regression
    ss_tot = float(np.sum((e2 - np.mean(e2)) ** 2))
    ss_res = float(np.sum(resid_aux**2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # LM statistic
    lm_stat = float(n * r2)
    df = k - 1  # degrees of freedom (exclude constant)
    lm_p_value = float(stats.chi2.sf(lm_stat, df=df))

    # F statistic variant
    if n - k > 0 and (1.0 - r2) > 0:
        f_stat = float((r2 / df) / ((1.0 - r2) / (n - k)))
        f_p_value = float(stats.f.sf(f_stat, df, n - k))
    else:
        f_stat = 0.0
        f_p_value = 1.0

    is_homoskedastic = bool(lm_p_value >= 0.05)

    return {
        "lm_statistic": lm_stat,
        "lm_p_value": lm_p_value,
        "f_statistic": float(f_stat),
        "f_p_value": float(f_p_value),
        "r_squared_aux": float(r2),
        "df": int(df),
        "n_obs": int(n),
        "is_homoskedastic": is_homoskedastic,
    }
