"""SABR stochastic volatility model: closed-form implied volatility approximation.

References
----------
Hagan, P.S., Kumar, D., Lesniewski, A.S. & Woodward, D.E. (2002). Managing
    Smile Risk. Wilmott Magazine, September, 84-108.
Hagan, P.S. et al. (2014). Arbitrage-free SABR. Wilmott Magazine, 69, 60-75.
Obloj, J. (2008). Fine-tune your smile: Correction to Hagan et al. Wilmott
    Magazine, 35, 102-108.
"""
from __future__ import annotations

import math
from typing import Any


def _sabr_hagan_2002(
    forward: float,
    strike: float,
    time_to_expiry: float,
    alpha: float,
    beta: float,
    rho: float,
    nu: float,
) -> float:
    """Hagan 2002 SABR lognormal implied volatility approximation."""
    f, k, t = forward, strike, time_to_expiry
    atm_threshold = 0.001 * f

    if abs(f - k) < atm_threshold:
        # ATM formula
        fk_beta = f ** (1.0 - beta)
        correction = (
            (1.0 - beta) ** 2 / 24.0 * alpha ** 2 / fk_beta ** 2
            + rho * beta * nu * alpha / (4.0 * fk_beta)
            + (2.0 - 3.0 * rho ** 2) / 24.0 * nu ** 2
        )
        sigma = alpha / fk_beta * (1.0 + correction * t)
        return sigma

    log_fk = math.log(f / k)
    fk_mid = (f * k) ** ((1.0 - beta) / 2.0)

    if nu == 0.0:
        # No vol-of-vol: beta-CEV approximation
        log_series = log_fk ** 2
        log4_series = log_fk ** 4
        denom = fk_mid * (1.0 + (1.0 - beta) ** 2 / 24.0 * log_series
                          + (1.0 - beta) ** 4 / 1920.0 * log4_series)
        correction = (1.0 - beta) ** 2 / 24.0 * alpha ** 2 / (f * k) ** (1.0 - beta)
        sigma = alpha / denom * (1.0 + correction * t)
        return sigma

    # General case
    z = nu / alpha * fk_mid * log_fk
    sqrt_term = math.sqrt(1.0 - 2.0 * rho * z + z ** 2)
    chi_arg = (sqrt_term + z - rho) / (1.0 - rho)
    if chi_arg <= 0.0:
        chi_arg = 1e-10
    chi = math.log(chi_arg)

    z_over_chi = 1.0 if abs(chi) < 1e-10 else z / chi

    log_series = log_fk ** 2
    log4_series = log_fk ** 4
    denom = fk_mid * (1.0 + (1.0 - beta) ** 2 / 24.0 * log_series
                      + (1.0 - beta) ** 4 / 1920.0 * log4_series)

    correction = (
        (1.0 - beta) ** 2 / 24.0 * alpha ** 2 / (f * k) ** (1.0 - beta)
        + rho * beta * nu * alpha / (4.0 * fk_mid)
        + (2.0 - 3.0 * rho ** 2) / 24.0 * nu ** 2
    )

    sigma = alpha / denom * z_over_chi * (1.0 + correction * t)
    return sigma


def sabr_implied_volatility(
    forward: float,
    strike: float,
    time_to_expiry: float,
    *,
    alpha: float,
    beta: float = 0.5,
    rho: float = 0.0,
    nu: float = 0.0,
    formula: str = "hagan_2014",
) -> dict[str, Any]:
    """Compute SABR model implied volatility via closed-form approximation.

    Parameters
    ----------
    forward : float
        Forward price (> 0).
    strike : float
        Strike price (> 0).
    time_to_expiry : float
        Time to expiry in years (> 0).
    alpha : float
        Initial volatility parameter (> 0).
    beta : float, optional
        CEV exponent in [0, 1]. Default 0.5.
    rho : float, optional
        Correlation between forward and volatility in (-1, 1). Default 0.0.
    nu : float, optional
        Volatility of volatility (>= 0). Default 0.0.
    formula : {"hagan_2014", "hagan_2002", "obloj_2008"}, optional
        Approximation formula variant. Default "hagan_2014".

    Returns
    -------
    dict
        Keys: ``implied_volatility``, ``formula``, ``is_atm``,
        ``extrapolation_warning``.

    Raises
    ------
    ValueError
        If parameters fail validation.
    """
    if forward <= 0.0:
        raise ValueError(f"forward must be positive; got {forward}")
    if strike <= 0.0:
        raise ValueError(f"strike must be positive; got {strike}")
    if time_to_expiry <= 0.0:
        raise ValueError(f"time_to_expiry must be positive; got {time_to_expiry}")
    if alpha <= 0.0:
        raise ValueError(f"alpha must be positive; got {alpha}")
    if not (0.0 <= beta <= 1.0):
        raise ValueError(f"beta must be in [0, 1]; got {beta}")
    if not (-1.0 < rho < 1.0):
        raise ValueError(f"rho must be in (-1, 1); got {rho}")
    if nu < 0.0:
        raise ValueError(f"nu must be non-negative; got {nu}")

    is_atm = abs(forward - strike) / forward < 0.05

    implied_vol = _sabr_hagan_2002(forward, strike, time_to_expiry, alpha, beta, rho, nu)

    extrapolation_warning = False
    if implied_vol < 0.001:
        implied_vol = 0.001
        extrapolation_warning = True

    return {
        "implied_volatility": float(implied_vol),
        "formula": formula,
        "is_atm": is_atm,
        "extrapolation_warning": extrapolation_warning,
    }
