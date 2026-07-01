"""EGARCH(1,1) volatility model.

References
----------
Nelson, D.B. (1991). Conditional Heteroskedasticity in Asset Returns:
    A New Approach. Econometrica, 59(2), 347-370.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy.optimize import minimize

# E[|z|] for standard normal = sqrt(2/pi)
_SQRT_2_OVER_PI = float(np.sqrt(2.0 / np.pi))


def _egarch11_nll(params: np.ndarray, returns: np.ndarray) -> float:
    """Negative log-likelihood for EGARCH(1,1) with normal errors."""
    omega, alpha, gamma, beta, mu = params
    # Stability: |beta| < 1
    if abs(beta) >= 1.0:
        return 1e10
    T = len(returns)
    eps = returns - mu
    log_sigma2 = np.zeros(T)
    log_sigma2[0] = np.log(max(np.var(returns), 1e-8))
    for t in range(1, T):
        sigma_prev = np.exp(0.5 * log_sigma2[t - 1])
        if sigma_prev <= 0:
            return 1e10  # pragma: no cover
        z_prev = eps[t - 1] / sigma_prev
        log_sigma2[t] = (
            omega
            + alpha * (abs(z_prev) - _SQRT_2_OVER_PI)
            + gamma * z_prev
            + beta * log_sigma2[t - 1]
        )
    sigma2 = np.exp(log_sigma2)
    if np.any(~np.isfinite(sigma2)) or np.any(sigma2 <= 0):
        return 1e10  # pragma: no cover
    ll = -0.5 * np.sum(log_sigma2 + eps**2 / sigma2)
    return float(-ll)


def egarch_fit(
    returns,
    *,
    p: int = 1,
    q: int = 1,
    o: int = 1,
    distribution: str = "normal",
    max_iter: int = 1000,
) -> dict:
    """Fit an EGARCH(1,1) model via MLE.

    Key feature: variance is modeled in log-space, guaranteeing positivity
    without explicit constraints. The leverage term gamma captures asymmetric
    response (typically gamma < 0 for financial returns).

    Parameters
    ----------
    returns : array-like or pd.Series
        Return series. Requires at least 50 observations.
    p : int
        ARCH order (currently only p=1 supported).
    q : int
        GARCH order (currently only q=1 supported).
    o : int
        Leverage order (currently only o=1 supported).
    distribution : str
        Error distribution ("normal" supported). Default "normal".
    max_iter : int
        Maximum optimizer iterations. Default 1000.

    Returns
    -------
    dict
        Keys: params (omega, alpha, gamma, beta, mu), log_likelihood,
        aic, bic, persistence (|beta|), residuals,
        conditional_variance, converged.

    Raises
    ------
    ValueError
        If fewer than 50 observations.

    References
    ----------
    Nelson, D.B. (1991). Econometrica, 59(2), 347-370.
    """
    if isinstance(returns, pd.Series):
        arr = returns.to_numpy(dtype=float)
    else:
        arr = np.asarray(returns, dtype=float)

    if len(arr) < 50:
        raise ValueError(f"Need at least 50 observations, got {len(arr)}")

    if p != 1 or q != 1 or o != 1:
        warnings.warn(
            f"EGARCH({p},{q},{o}) not fully supported; fitting EGARCH(1,1).",
            UserWarning,
            stacklevel=2,
        )

    T = len(arr)
    mean_val = float(np.mean(arr))
    var_val = float(np.var(arr))

    # Initial guess
    x0 = np.array([
        np.log(max(var_val, 1e-8)) * 0.05,  # omega
        0.1,   # alpha
        -0.1,  # gamma (leverage: negative for typical equity)
        0.85,  # beta
        mean_val,  # mu
    ])

    # Try multiple starting points
    best_result = None
    best_nll = np.inf

    starts = [
        x0,
        np.array([-0.2, 0.05, -0.05, 0.90, mean_val]),
        np.array([-0.1, 0.15, -0.15, 0.80, mean_val]),
        np.array([-0.3, 0.08, 0.0, 0.88, mean_val]),
    ]

    for start in starts:
        try:
            result = minimize(
                _egarch11_nll,
                start,
                args=(arr,),
                method="Nelder-Mead",
                options={"maxiter": max_iter, "xatol": 1e-6, "fatol": 1e-6},
            )
            if result.fun < best_nll:
                best_nll = result.fun
                best_result = result
        except Exception:  # pragma: no cover
            continue

    if best_result is None:
        best_result = minimize(
            _egarch11_nll,
            x0,
            args=(arr,),
            method="Nelder-Mead",
            options={"maxiter": max_iter},
        )

    omega, alpha, gamma, beta, mu = best_result.x
    params = {
        "omega": float(omega),
        "alpha": float(alpha),
        "gamma": float(gamma),
        "beta": float(beta),
        "mu": float(mu),
    }

    # Compute final conditional variance series
    eps = arr - mu
    log_sigma2 = np.zeros(T)
    log_sigma2[0] = np.log(max(float(np.var(arr)), 1e-8))
    for t in range(1, T):
        sigma_prev = np.exp(0.5 * log_sigma2[t - 1])
        z_prev = eps[t - 1] / max(sigma_prev, 1e-10)
        log_sigma2[t] = (
            omega
            + alpha * (abs(z_prev) - _SQRT_2_OVER_PI)
            + gamma * z_prev
            + beta * log_sigma2[t - 1]
        )
    conditional_variance = np.exp(log_sigma2)

    log_likelihood = float(-best_result.fun)
    k = 5
    aic = float(-2 * log_likelihood + 2 * k)
    bic = float(-2 * log_likelihood + k * np.log(T))

    return {
        "params": params,
        "log_likelihood": log_likelihood,
        "aic": aic,
        "bic": bic,
        "persistence": float(abs(beta)),
        "residuals": eps,
        "conditional_variance": conditional_variance,
        "converged": bool(best_result.success),
    }


def egarch_forecast(
    params: dict,
    last_z: float,
    last_log_variance: float,
    *,
    horizon: int = 1,
) -> np.ndarray:
    """Forecast conditional variance from a fitted EGARCH(1,1) model.

    One-step forecast: recursion using last standardized residual.
    Multi-step: uses analytical approximation in log-space.

    Parameters
    ----------
    params : dict
        Dictionary with keys omega, alpha, gamma, beta.
    last_z : float
        Last standardized residual z_{t} = eps_t / sigma_t.
    last_log_variance : float
        Last log-conditional variance log(sigma_t^2).
    horizon : int
        Forecast horizon.

    Returns
    -------
    np.ndarray
        Array of length horizon with forecast variances (not log-variance).

    References
    ----------
    Nelson, D.B. (1991). Econometrica, 59(2), 347-370.
    """
    omega = float(params["omega"])
    alpha = float(params["alpha"])
    gamma = float(params["gamma"])
    beta = float(params["beta"])

    forecast_log_var = np.zeros(horizon)

    # One-step: use actual last_z
    forecast_log_var[0] = (
        omega
        + alpha * (abs(last_z) - _SQRT_2_OVER_PI)
        + gamma * last_z
        + beta * last_log_variance
    )

    # Multi-step: E[log_sigma2_{t+h}] using analytical recursion
    # E[alpha*(|z| - E|z|) + gamma*z] = 0 (for standard normal z)
    # So: E[log_sigma2_{t+h}] = omega + beta * E[log_sigma2_{t+h-1}]
    # → E[log_sigma2_{t+h}] = omega*(1 + beta + ... + beta^{h-1}) + beta^h * log_sigma2_t
    for h in range(1, horizon):
        if abs(beta) < 1.0:
            forecast_log_var[h] = (
                omega * (1.0 - beta**h) / (1.0 - beta)
                + beta**h * last_log_variance
            )
        else:
            forecast_log_var[h] = forecast_log_var[h - 1]

    return np.exp(forecast_log_var)
