"""GJR-GARCH(1,1) volatility model (Glosten-Jagannathan-Runkle).

References
----------
Glosten, L.R., Jagannathan, R. & Runkle, D.E. (1993). On the Relation between
    the Expected Value and the Volatility of the Nominal Excess Return on Stocks.
    Journal of Finance, 48(5), 1779-1801.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def _gjrgarch11_nll(params: np.ndarray, returns: np.ndarray) -> float:
    """Negative log-likelihood for GJR-GARCH(1,1)."""
    omega, alpha, gamma, beta, mu = params
    # Positivity and stability constraints
    if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
        return 1e10
    # Stability: alpha + gamma/2 + beta < 1
    if alpha + gamma / 2.0 + beta >= 1.0:
        return 1e10

    T = len(returns)
    eps = returns - mu
    sigma2 = np.zeros(T)
    sigma2[0] = max(np.var(returns), 1e-8)

    for t in range(1, T):
        indicator = 1.0 if eps[t - 1] < 0 else 0.0
        sigma2[t] = (
            omega
            + alpha * eps[t - 1] ** 2
            + gamma * indicator * eps[t - 1] ** 2
            + beta * sigma2[t - 1]
        )
        if sigma2[t] <= 0:
            return 1e10  # pragma: no cover

    if np.any(sigma2 <= 0):
        return 1e10  # pragma: no cover
    ll = -0.5 * np.sum(np.log(sigma2) + eps**2 / sigma2)
    return float(-ll)


def gjr_garch_fit(
    returns,
    *,
    p: int = 1,
    q: int = 1,
    o: int = 1,
    distribution: str = "normal",
    max_iter: int = 1000,
) -> dict:
    """Fit a GJR-GARCH(1,1) model via MLE.

    GJR-GARCH extends GARCH by adding an asymmetric term: negative shocks
    have a larger impact on volatility (leverage effect).

    sigma2_t = omega + alpha*eps_{t-1}^2 + gamma*I(eps_{t-1}<0)*eps_{t-1}^2 + beta*sigma2_{t-1}

    Stability condition: alpha + gamma/2 + beta < 1.

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
        aic, bic, persistence (alpha + gamma/2 + beta),
        unconditional_variance, residuals, conditional_variance, converged.

    Raises
    ------
    ValueError
        If fewer than 50 observations.

    References
    ----------
    Glosten, Jagannathan & Runkle (1993). Journal of Finance, 48(5), 1779-1801.
    """
    if isinstance(returns, pd.Series):
        arr = returns.to_numpy(dtype=float)
    else:
        arr = np.asarray(returns, dtype=float)

    if len(arr) < 50:
        raise ValueError(f"Need at least 50 observations, got {len(arr)}")

    if p != 1 or q != 1 or o != 1:
        warnings.warn(
            f"GJR-GARCH({p},{q},{o}) not fully supported; fitting GJR-GARCH(1,1).",
            UserWarning,
            stacklevel=2,
        )

    T = len(arr)
    mean_val = float(np.mean(arr))
    var_val = float(np.var(arr))

    x0 = np.array([
        var_val * 0.05,  # omega
        0.05,  # alpha
        0.10,  # gamma (asymmetry: should be positive for leverage effect)
        0.80,  # beta
        mean_val,  # mu
    ])

    bounds = [
        (1e-8, None),  # omega > 0
        (1e-8, 0.999),  # alpha >= 0
        (1e-8, 0.999),  # gamma >= 0
        (1e-8, 0.999),  # beta >= 0
        (None, None),   # mu unrestricted
    ]

    # Try multiple starting points
    starts = [
        x0,
        np.array([var_val * 0.03, 0.08, 0.15, 0.75, mean_val]),
        np.array([var_val * 0.08, 0.03, 0.07, 0.85, mean_val]),
        np.array([var_val * 0.02, 0.10, 0.05, 0.82, mean_val]),
    ]

    best_result = None
    best_nll = np.inf

    for start in starts:
        try:
            result = minimize(
                _gjrgarch11_nll,
                start,
                args=(arr,),
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": max_iter, "ftol": 1e-12},
            )
            if result.fun < best_nll:
                best_nll = result.fun
                best_result = result
        except Exception:  # pragma: no cover
            continue

    if best_result is None:  # pragma: no cover
        best_result = minimize(
            _gjrgarch11_nll,
            x0,
            args=(arr,),
            method="L-BFGS-B",
            bounds=bounds,
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
    sigma2 = np.zeros(T)
    sigma2[0] = max(var_val, 1e-8)
    for t in range(1, T):
        indicator = 1.0 if eps[t - 1] < 0 else 0.0
        sigma2[t] = omega + alpha * eps[t - 1] ** 2 + gamma * indicator * eps[t - 1] ** 2 + beta * sigma2[t - 1]

    log_likelihood = float(-best_result.fun)
    k = 5
    aic = float(-2 * log_likelihood + 2 * k)
    bic = float(-2 * log_likelihood + k * np.log(T))

    persistence = float(alpha + gamma / 2.0 + beta)
    if persistence < 1.0:
        unconditional_variance = float(omega / (1.0 - persistence))
    else:
        unconditional_variance = float("nan")

    return {
        "params": params,
        "log_likelihood": log_likelihood,
        "aic": aic,
        "bic": bic,
        "persistence": persistence,
        "unconditional_variance": unconditional_variance,
        "residuals": eps,
        "conditional_variance": sigma2,
        "converged": bool(best_result.success),
    }


def gjr_garch_forecast(
    params: dict,
    last_eps2: float,
    last_sigma2: float,
    *,
    horizon: int = 1,
    expected_neg_frac: float = 0.5,
) -> np.ndarray:
    """Forecast conditional variance from a fitted GJR-GARCH(1,1) model.

    Parameters
    ----------
    params : dict
        Dictionary with keys omega, alpha, gamma, beta.
    last_eps2 : float
        Most recent squared residual eps_t^2.
    last_sigma2 : float
        Most recent conditional variance sigma_t^2.
    horizon : int
        Forecast horizon.
    expected_neg_frac : float
        E[I(eps<0)], the probability of a negative shock. Default 0.5
        (symmetric distribution).

    Returns
    -------
    np.ndarray
        Array of length horizon with forecast variances.

    References
    ----------
    Glosten, Jagannathan & Runkle (1993). Journal of Finance, 48(5), 1779-1801.
    """
    omega = float(params["omega"])
    alpha = float(params["alpha"])
    gamma = float(params["gamma"])
    beta = float(params["beta"])

    # Effective ARCH coefficient accounting for leverage: alpha + gamma * E[I<0]
    eff_alpha = alpha + gamma * expected_neg_frac
    persistence = eff_alpha + beta

    forecast_var = np.zeros(horizon)

    # One-step: use last actual eps^2
    forecast_var[0] = (
        omega
        + alpha * last_eps2
        + gamma * expected_neg_frac * last_eps2
        + beta * last_sigma2
    )

    # Multi-step: E[sigma2_{t+h}] using long-run mean reversion
    for h in range(1, horizon):
        forecast_var[h] = omega + persistence * forecast_var[h - 1]

    return forecast_var
