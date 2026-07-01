"""Monte Carlo option pricing: European and Asian options.

References
----------
Glasserman, P. (2004). Monte Carlo Methods in Financial Engineering.
    Springer, New York.
Hull, J.C. (2018). Options, Futures, and Other Derivatives (10th ed.).
    Pearson Education.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np


def _bs_call_price(S: float, K: float, T: float, r: float, sigma: float, q: float) -> float:
    """Closed-form Black-Scholes call price for control variate."""
    from scipy.stats import norm
    if T <= 0 or sigma <= 0:
        return max(S * np.exp(-q * T) - K * np.exp(-r * T), 0.0)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    return float(
        S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    )


def mc_european_price(
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    volatility: float,
    *,
    n_simulations: int = 10000,
    option_type: Literal["call", "put"] = "call",
    dividend_yield: float = 0.0,
    seed: int | None = None,
    antithetic: bool = True,
    control_variate: bool = False,
) -> dict[str, Any]:
    """Price a European option via Monte Carlo simulation.

    Parameters
    ----------
    spot : float
        Current asset price (> 0).
    strike : float
        Strike price (> 0).
    time_to_expiry : float
        Time to expiry in years (>= 0).
    risk_free_rate : float
        Continuously compounded risk-free rate.
    volatility : float
        Annual volatility (>= 0).
    n_simulations : int
        Number of simulated paths. Default 10000.
    option_type : {"call", "put"}
        Default "call".
    dividend_yield : float
        Continuous dividend yield. Default 0.0.
    seed : int or None
        Random seed for reproducibility.
    antithetic : bool
        Use antithetic variates for variance reduction. Default True.
    control_variate : bool
        Use Black-Scholes as control variate. Default False.

    Returns
    -------
    dict with keys:
        price, standard_error, 95_confidence_interval, n_simulations_used, method.

    Raises
    ------
    ValueError
        If inputs are invalid.

    References
    ----------
    Glasserman (2004). Monte Carlo Methods in Financial Engineering.
    """
    if spot <= 0:
        raise ValueError(f"spot must be > 0, got {spot}")
    if strike <= 0:
        raise ValueError(f"strike must be > 0, got {strike}")
    if time_to_expiry < 0:
        raise ValueError(f"time_to_expiry must be >= 0, got {time_to_expiry}")
    if volatility < 0:
        raise ValueError(f"volatility must be >= 0, got {volatility}")
    if n_simulations < 1:
        raise ValueError(f"n_simulations must be >= 1, got {n_simulations}")
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")

    S, K, T, r, sigma, q = spot, strike, time_to_expiry, risk_free_rate, volatility, dividend_yield

    # Edge case: T=0
    if T == 0:
        if option_type == "call":
            price = float(max(S - K, 0.0))
        else:
            price = float(max(K - S, 0.0))
        return {
            "price": price,
            "standard_error": 0.0,
            "95_confidence_interval": (price, price),
            "n_simulations_used": 0,
            "method": "analytic_at_expiry",
        }

    rng = np.random.default_rng(seed)

    drift = (r - q - 0.5 * sigma**2) * T
    vol_sqrt_T = sigma * np.sqrt(T)

    method_parts = []

    if antithetic:
        half_n = n_simulations // 2 if n_simulations > 1 else 1
        Z = rng.standard_normal(half_n)
        Z_full = np.concatenate([Z, -Z])
        method_parts.append("antithetic")
    else:
        Z_full = rng.standard_normal(n_simulations)

    n_used = len(Z_full)

    if sigma == 0:
        ST = S * np.exp(drift * np.ones(n_used))
    else:
        ST = S * np.exp(drift + vol_sqrt_T * Z_full)

    # Discounted payoff
    disc = np.exp(-r * T)
    if option_type == "call":
        payoffs = disc * np.maximum(ST - K, 0.0)
    else:
        payoffs = disc * np.maximum(K - ST, 0.0)

    if control_variate and sigma > 0:
        # Control variate: use log(ST/S) as normal control
        # E[ST] = S * exp((r-q)*T)
        ST_mean_analytic = S * np.exp((r - q) * T)
        beta = -np.cov(payoffs, ST)[0, 1] / np.var(ST)
        payoffs_cv = payoffs + beta * (ST - ST_mean_analytic)
        payoffs = payoffs_cv
        method_parts.append("control_variate")

    price_est = float(np.mean(payoffs))
    se = float(np.std(payoffs, ddof=1) / np.sqrt(n_used))
    ci_low = price_est - 1.96 * se
    ci_high = price_est + 1.96 * se

    method_str = "monte_carlo[" + ",".join(method_parts) + "]" if method_parts else "monte_carlo"

    return {
        "price": price_est,
        "standard_error": se,
        "95_confidence_interval": (ci_low, ci_high),
        "n_simulations_used": n_used,
        "method": method_str,
    }


def mc_asian_price(
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    volatility: float,
    *,
    n_simulations: int = 10000,
    n_averaging_dates: int = 252,
    option_type: Literal["call", "put"] = "call",
    averaging: Literal["arithmetic", "geometric"] = "arithmetic",
    strike_type: Literal["fixed", "floating"] = "fixed",
    dividend_yield: float = 0.0,
    seed: int | None = None,
) -> dict[str, Any]:
    """Price an Asian option via Monte Carlo simulation.

    Parameters
    ----------
    spot : float
        Current asset price (> 0).
    strike : float
        Strike price for fixed-strike options (> 0).
    time_to_expiry : float
        Time to expiry in years (>= 0).
    risk_free_rate : float
        Continuously compounded risk-free rate.
    volatility : float
        Annual volatility (>= 0).
    n_simulations : int
        Number of simulated paths. Default 10000.
    n_averaging_dates : int
        Number of averaging dates. Default 252.
    option_type : {"call", "put"}
        Default "call".
    averaging : {"arithmetic", "geometric"}
        Averaging method. Default "arithmetic".
    strike_type : {"fixed", "floating"}
        Fixed: payoff based on avg vs K. Floating: payoff based on S_T vs avg.
    dividend_yield : float
        Continuous dividend yield. Default 0.0.
    seed : int or None
        Random seed.

    Returns
    -------
    dict with keys:
        price, standard_error, 95_confidence_interval, averaging.

    Raises
    ------
    ValueError
        If inputs are invalid.

    References
    ----------
    Glasserman (2004). Monte Carlo Methods in Financial Engineering. Ch. 4.
    """
    if spot <= 0:
        raise ValueError(f"spot must be > 0, got {spot}")
    if strike <= 0:
        raise ValueError(f"strike must be > 0, got {strike}")
    if time_to_expiry < 0:
        raise ValueError(f"time_to_expiry must be >= 0, got {time_to_expiry}")
    if volatility < 0:
        raise ValueError(f"volatility must be >= 0, got {volatility}")
    if n_simulations < 1:
        raise ValueError(f"n_simulations must be >= 1, got {n_simulations}")
    if n_averaging_dates < 1:
        raise ValueError(f"n_averaging_dates must be >= 1, got {n_averaging_dates}")
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")
    if averaging not in ("arithmetic", "geometric"):
        raise ValueError(f"averaging must be 'arithmetic' or 'geometric', got {averaging!r}")
    if strike_type not in ("fixed", "floating"):
        raise ValueError(f"strike_type must be 'fixed' or 'floating', got {strike_type!r}")

    S, K, T, r, sigma, q = spot, strike, time_to_expiry, risk_free_rate, volatility, dividend_yield

    if T == 0:
        price = float(max(S - K, 0.0)) if option_type == "call" else float(max(K - S, 0.0))
        return {
            "price": price,
            "standard_error": 0.0,
            "95_confidence_interval": (price, price),
            "averaging": averaging,
        }

    rng = np.random.default_rng(seed)
    dt = T / n_averaging_dates
    drift = (r - q - 0.5 * sigma**2) * dt
    vol_sqrt_dt = sigma * np.sqrt(dt)

    # Simulate paths: shape (n_simulations, n_averaging_dates)
    Z = rng.standard_normal((n_simulations, n_averaging_dates))
    # Log increments
    log_increments = drift + vol_sqrt_dt * Z
    # Cumulative log paths → asset prices at each date
    log_paths = np.cumsum(log_increments, axis=1)
    paths = S * np.exp(log_paths)  # shape (n_sims, n_dates)

    # Terminal price
    ST = paths[:, -1]

    # Compute average
    if averaging == "arithmetic":
        avg = np.mean(paths, axis=1)
    else:  # geometric
        avg = np.exp(np.mean(np.log(paths), axis=1))

    # Payoff
    disc = np.exp(-r * T)
    if strike_type == "fixed":
        if option_type == "call":
            payoffs = disc * np.maximum(avg - K, 0.0)
        else:
            payoffs = disc * np.maximum(K - avg, 0.0)
    else:  # floating
        if option_type == "call":
            payoffs = disc * np.maximum(ST - avg, 0.0)
        else:
            payoffs = disc * np.maximum(avg - ST, 0.0)

    price_est = float(np.mean(payoffs))
    se = float(np.std(payoffs, ddof=1) / np.sqrt(n_simulations))
    ci_low = price_est - 1.96 * se
    ci_high = price_est + 1.96 * se

    return {
        "price": price_est,
        "standard_error": se,
        "95_confidence_interval": (ci_low, ci_high),
        "averaging": averaging,
    }
