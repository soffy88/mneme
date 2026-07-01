"""GARCH(1,1) volatility model.

References
----------
Bollerslev, T. (1986). Generalized Autoregressive Conditional
    Heteroskedasticity. Journal of Econometrics, 31(3), 307-327.
Hamilton, J.D. (1994). Time Series Analysis. Princeton University Press.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def _garch11_nll(params, returns):
    """Negative log-likelihood for GARCH(1,1)."""
    omega, alpha, beta, mu = params
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1:
        return 1e10
    T = len(returns)
    eps = returns - mu
    sigma2 = np.zeros(T)
    sigma2[0] = np.var(returns)
    for t in range(1, T):
        sigma2[t] = omega + alpha * eps[t - 1] ** 2 + beta * sigma2[t - 1]
    if np.any(sigma2 <= 0):
        return 1e10  # pragma: no cover
    ll = -0.5 * np.sum(np.log(sigma2) + eps**2 / sigma2)
    return -ll  # return negative log-likelihood


def garch_fit(
    returns,
    *,
    p: int = 1,
    q: int = 1,
    mean: str = "constant",
    distribution: str = "normal",
    max_iter: int = 1000,
) -> dict:
    """Fit a GARCH(p,q) model via MLE.

    Currently fully supports GARCH(1,1). Warns for p>1 or q>1.

    Parameters
    ----------
    returns : array-like or pd.Series
        Return series. Requires at least 50 observations.
    p : int, optional
        ARCH order. Default 1.
    q : int, optional
        GARCH order. Default 1.
    mean : str, optional
        Mean model ("constant" supported). Default "constant".
    distribution : str, optional
        Error distribution ("normal", "t"). Default "normal".
    max_iter : int, optional
        Maximum optimizer iterations. Default 1000.

    Returns
    -------
    dict
        Keys: ``params``, ``log_likelihood``, ``aic``, ``bic``,
        ``persistence``, ``unconditional_variance``, ``converged``,
        ``residuals``, ``conditional_variance``.

    Raises
    ------
    ValueError
        If fewer than 50 observations.

    References
    ----------
    Bollerslev, T. (1986). Generalized Autoregressive Conditional
    Heteroskedasticity. Journal of Econometrics, 31(3), 307-327.
    """
    if isinstance(returns, pd.Series):
        arr = returns.to_numpy(dtype=float)
    else:
        arr = np.asarray(returns, dtype=float)

    if len(arr) < 50:
        raise ValueError(f"Need at least 50 observations, got {len(arr)}")

    if p > 1 or q > 1:
        warnings.warn(
            f"GARCH({p},{q}) not fully supported; falling back to GARCH(1,1).",
            UserWarning,
            stacklevel=2,
        )

    T = len(arr)
    mean_val = float(np.mean(arr))
    var_val = float(np.var(arr))

    x0 = np.array([var_val * 0.05, 0.1, 0.8, mean_val])
    bounds = [(1e-8, None), (1e-8, 0.999), (1e-8, 0.999), (None, None)]

    result = minimize(
        _garch11_nll,
        x0,
        args=(arr,),
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": max_iter, "ftol": 1e-12},
    )

    omega, alpha, beta, mu = result.x
    params = {
        "omega": float(omega),
        "alpha": float(alpha),
        "beta": float(beta),
        "mu": float(mu),
    }

    # Compute final conditional variance series
    eps = arr - mu
    sigma2 = np.zeros(T)
    sigma2[0] = var_val
    for t in range(1, T):
        sigma2[t] = omega + alpha * eps[t - 1] ** 2 + beta * sigma2[t - 1]

    log_likelihood = float(-result.fun)
    k = 4  # omega, alpha, beta, mu
    aic = float(-2 * log_likelihood + 2 * k)
    bic = float(-2 * log_likelihood + k * np.log(T))

    persistence = float(alpha + beta)
    if persistence < 1:
        unconditional_variance = float(omega / (1.0 - alpha - beta))
    else:
        unconditional_variance = float("nan")

    return {
        "params": params,
        "log_likelihood": log_likelihood,
        "aic": aic,
        "bic": bic,
        "persistence": persistence,
        "unconditional_variance": unconditional_variance,
        "converged": bool(result.success),
        "residuals": eps,
        "conditional_variance": sigma2,
    }


def garch_forecast(
    params: dict,
    last_residual: float,
    last_variance: float,
    *,
    horizon: int = 1,
    p: int = 1,
    q: int = 1,
) -> np.ndarray:
    """Forecast conditional variance from a GARCH(1,1) model.

    Does NOT import or call ``garch_fit``.

    Parameters
    ----------
    params : dict
        Dictionary with keys ``omega``, ``alpha``, ``beta``.
    last_residual : float
        Most recent residual eps_t.
    last_variance : float
        Most recent conditional variance sigma_t^2.
    horizon : int, optional
        Forecast horizon. Default 1.
    p : int, optional
        Unused (kept for API compatibility).
    q : int, optional
        Unused (kept for API compatibility).

    Returns
    -------
    np.ndarray
        Array of length ``horizon`` with forecast variances (in std dev).

    References
    ----------
    Bollerslev, T. (1986). Journal of Econometrics, 31(3), 307-327.
    Hamilton, J.D. (1994). Time Series Analysis. Princeton University Press.
    """
    omega = float(params["omega"])
    alpha = float(params["alpha"])
    beta = float(params["beta"])
    persistence = alpha + beta

    if persistence >= 1:
        warnings.warn(
            f"GARCH persistence alpha+beta={persistence:.4f} >= 1 (unit root). "
            "Forecasts may be unreliable.",
            RuntimeWarning,
            stacklevel=2,
        )

    forecast_var = np.zeros(horizon)

    # 1-step ahead: h=1
    forecast_var[0] = omega + alpha * last_residual**2 + beta * last_variance

    # h-step ahead: recursive using long-run mean reversion
    for h in range(1, horizon):
        forecast_var[h] = omega + persistence * forecast_var[h - 1]

    return forecast_var
