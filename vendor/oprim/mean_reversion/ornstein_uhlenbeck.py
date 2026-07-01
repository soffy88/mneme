"""Ornstein-Uhlenbeck process estimation.

References
----------
Smith, J.E. (2010). On the Simulation and Estimation of the Mean-Reverting
    Ornstein-Uhlenbeck Process. Especially closed-form MLE.
López de Prado, M. (2018). Advances in Financial Machine Learning, Ch.4.
Chan, E. (2013). Algorithmic Trading.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def ornstein_uhlenbeck_fit(series, *, dt: float = 1.0) -> dict:
    """Fit Ornstein-Uhlenbeck process parameters via closed-form MLE.

    Parameters
    ----------
    series : array-like or pd.Series
        Time series of the process (at least 30 observations).
    dt : float, optional
        Time step between observations. Default 1.0.

    Returns
    -------
    dict
        Keys: ``theta``, ``mu``, ``sigma``, ``half_life``.
        If theta <= 0 (no mean reversion), values are NaN.

    Raises
    ------
    ValueError
        If len(series) < 30.

    References
    ----------
    Smith, J.E. (2010). On the Simulation and Estimation of the Mean-Reverting
    OU Process.
    """
    if isinstance(series, pd.Series):
        arr = series.to_numpy(dtype=float)
    else:
        arr = np.asarray(series, dtype=float)

    if len(arr) < 30:
        raise ValueError(f"Need at least 30 observations, got {len(arr)}")

    X = arr[:-1]
    Y = arr[1:]

    # Closed-form MLE: correlation-based estimator
    rho = float(np.corrcoef(X, Y)[0, 1])

    # Guard against rho <= 0 (random walk or anti-mean-reversion)
    if rho <= 0:
        nan = float("nan")
        return {"theta": nan, "mu": nan, "sigma": nan, "half_life": nan}

    theta = -math.log(rho) / dt

    if theta <= 0:
        nan = float("nan")
        return {"theta": nan, "mu": nan, "sigma": nan, "half_life": nan}

    mu = float(np.mean(arr) / (1.0 - rho))

    residuals = Y - rho * X
    sigma2 = float(np.var(residuals) * 2.0 * theta / (1.0 - rho**2))
    sigma = math.sqrt(max(sigma2, 0.0))
    half_life = math.log(2.0) / theta

    return {
        "theta": float(theta),
        "mu": float(mu),
        "sigma": sigma,
        "half_life": float(half_life),
    }


def ornstein_uhlenbeck_half_life(series, *, method: str = "regression") -> float:
    """Estimate half-life of mean reversion for an OU process.

    Does NOT import or call ``ornstein_uhlenbeck_fit``.

    Parameters
    ----------
    series : array-like or pd.Series
        Time series of the process.
    method : {"regression", "mle"}, optional
        Estimation method. Default "regression".

    Returns
    -------
    float
        Half-life in same units as observation spacing. Returns ``inf`` if
        no mean reversion detected, or ``nan`` if computation fails.

    Raises
    ------
    ValueError
        If method is unknown.

    References
    ----------
    López de Prado, M. (2018). Advances in Financial Machine Learning, Ch.4.
    Chan, E. (2013). Algorithmic Trading.
    """
    if isinstance(series, pd.Series):
        arr = series.to_numpy(dtype=float)
    else:
        arr = np.asarray(series, dtype=float)

    if method == "regression":
        # OLS: dX_t = beta * X_{t-1} + eps
        dX = arr[1:] - arr[:-1]
        X_lag = arr[:-1]
        cov = float(np.cov(dX, X_lag)[0, 1])
        var = float(np.var(X_lag, ddof=1))
        if var == 0:
            return float("nan")
        beta = cov / var
        theta = -beta
        if theta <= 0:
            return float("inf")
        return math.log(2.0) / theta

    elif method == "mle":
        # Inline MLE theta computation (no import of ornstein_uhlenbeck_fit)
        X = arr[:-1]
        Y = arr[1:]
        rho = float(np.corrcoef(X, Y)[0, 1])
        if rho <= 0:
            return float("inf")
        theta = -math.log(rho)  # dt=1.0
        if theta <= 0:
            return float("inf")
        return math.log(2.0) / theta

    else:
        raise ValueError(f"Unknown method '{method}'. Expected 'regression' or 'mle'.")
