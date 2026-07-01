"""Exotic option pricing: barrier and lookback options.

References
----------
Reiner, E. & Rubinstein, M. (1991). Breaking Down the Barriers.
    Risk Magazine, 4(8), 28-35.
Goldman, M.B., Sosin, H.B. & Gatto, M.A. (1979). Path Dependent Options:
    Buy at the Low, Sell at the High. Journal of Finance, 34(5), 1111-1127.
Haug, E.G. (2007). The Complete Guide to Option Pricing Formulas (2nd ed.).
    McGraw-Hill.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np
from scipy.stats import norm


def _bs_vanilla(S: float, K: float, T: float, r: float, sigma: float, q: float,
                option_type: str) -> float:
    """Black-Scholes vanilla price for parity relations."""
    if T <= 0:
        if option_type == "call":
            return max(S - K, 0.0)
        return max(K - S, 0.0)
    if sigma <= 0:
        if option_type == "call":
            return max(S * np.exp(-q * T) - K * np.exp(-r * T), 0.0)
        return max(K * np.exp(-r * T) - S * np.exp(-q * T), 0.0)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    call = S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    if option_type == "call":
        return float(call)
    return float(call - S * np.exp(-q * T) + K * np.exp(-r * T))


def _barrier_cf(
    S: float, K: float, H: float, T: float, r: float, sigma: float, q: float,
    barrier_type: str, option_type: str, rebate: float,
) -> float:
    """Closed-form barrier option price using Reiner-Rubinstein (1991) formulas."""
    if T <= 0:
        ST = S  # at expiry, S is known
        if option_type == "call":
            intrinsic = max(S - K, 0.0)
        else:
            intrinsic = max(K - S, 0.0)
        if "out" in barrier_type:
            if "down" in barrier_type and S <= H:
                return rebate
            if "up" in barrier_type and S >= H:
                return rebate
            return intrinsic
        else:  # in
            if "down" in barrier_type and S <= H:
                return intrinsic
            if "up" in barrier_type and S >= H:
                return intrinsic
            return rebate

    if sigma <= 0:
        # Zero vol: deterministic path
        return _barrier_zero_vol(S, K, H, T, r, q, barrier_type, option_type, rebate)

    sqrt_T = np.sqrt(T)
    mu = (r - q - 0.5 * sigma**2) / sigma**2
    lambda_val = np.sqrt(mu**2 + 2.0 * r / sigma**2)

    x1 = np.log(S / K) / (sigma * sqrt_T) + (1.0 + mu) * sigma * sqrt_T
    x2 = np.log(S / H) / (sigma * sqrt_T) + (1.0 + mu) * sigma * sqrt_T
    y1 = np.log(H**2 / (S * K)) / (sigma * sqrt_T) + (1.0 + mu) * sigma * sqrt_T
    y2 = np.log(H / S) / (sigma * sqrt_T) + (1.0 + mu) * sigma * sqrt_T
    z = np.log(H / S) / (sigma * sqrt_T) + lambda_val * sigma * sqrt_T

    phi = 1.0 if option_type == "call" else -1.0
    eta: float  # direction multiplier: +1 for down barriers, -1 for up barriers

    N = norm.cdf
    disc_r = np.exp(-r * T)
    disc_q = np.exp(-q * T)

    # Component functions from Reiner-Rubinstein (1991)
    def A(phi_: float, x_: float) -> float:
        return phi_ * (
            S * disc_q * N(phi_ * x_)
            - K * disc_r * N(phi_ * (x_ - sigma * sqrt_T))
        )

    def B(phi_: float, x_: float) -> float:
        return phi_ * (
            S * disc_q * N(phi_ * x_)
            - K * disc_r * N(phi_ * (x_ - sigma * sqrt_T))
        )

    def C(phi_: float, eta_: float, y_: float) -> float:
        return phi_ * (
            S * disc_q * (H / S) ** (2.0 * (mu + 1.0)) * N(eta_ * y_)
            - K * disc_r * (H / S) ** (2.0 * mu) * N(eta_ * (y_ - sigma * sqrt_T))
        )

    def D(phi_: float, eta_: float, y_: float) -> float:
        return phi_ * (
            S * disc_q * (H / S) ** (2.0 * (mu + 1.0)) * N(eta_ * y_)
            - K * disc_r * (H / S) ** (2.0 * mu) * N(eta_ * (y_ - sigma * sqrt_T))
        )

    def E_rebate(eta_: float) -> float:
        return rebate * disc_r * (
            N(eta_ * (x2 - sigma * sqrt_T))
            - (H / S) ** (2.0 * mu) * N(eta_ * (y2 - sigma * sqrt_T))
        )

    def F_rebate(eta_: float) -> float:
        return rebate * (
            (H / S) ** (mu + lambda_val) * N(eta_ * z)
            + (H / S) ** (mu - lambda_val) * N(eta_ * (z - 2.0 * lambda_val * sigma * sqrt_T))
        )

    # Use parity: out + in = vanilla; derive all 8 cases
    vanilla = _bs_vanilla(S, K, T, r, sigma, q, option_type)

    if barrier_type == "down_and_out":
        if S <= H:
            return rebate  # already knocked out
        eta = 1.0
        if option_type == "call":
            if K >= H:
                price = A(phi, x1) - C(phi, eta, y1) + E_rebate(eta)
            else:
                price = B(phi, x2) - C(phi, eta, y1) + D(phi, eta, y2) + E_rebate(eta)
        else:  # put
            if K >= H:
                price = A(phi, x1) - B(phi, x2) + C(phi, eta, y1) - D(phi, eta, y2) + E_rebate(eta)
            else:
                price = E_rebate(eta)
        return float(max(price, 0.0))

    elif barrier_type == "down_and_in":
        if S <= H:
            return vanilla  # already knocked in
        out_price = barrier_option_price(
            S, K, H, T, r, sigma,
            barrier_type="down_and_out",
            option_type=option_type,
            rebate=0.0,
            dividend_yield=q,
            method="closed_form",
        )["price"]
        rebate_out = _barrier_cf(S, K, H, T, r, sigma, q, "down_and_out", option_type, rebate)
        # in + out = vanilla + rebate (the rebate is paid by the out)
        return float(vanilla - out_price + rebate * np.exp(-r * T))

    elif barrier_type == "up_and_out":
        if S >= H:
            return rebate  # already knocked out
        eta = -1.0
        if option_type == "call":
            if K >= H:
                price = E_rebate(eta)
            else:
                price = A(phi, x1) - B(phi, x2) + C(phi, eta, y1) - D(phi, eta, y2) + E_rebate(eta)
        else:  # put
            if K >= H:
                price = A(phi, x1) - C(phi, eta, y1) + E_rebate(eta)
            else:
                price = B(phi, x2) - D(phi, eta, y2) + E_rebate(eta)
        return float(max(price, 0.0))

    elif barrier_type == "up_and_in":
        if S >= H:
            return vanilla
        out_price = barrier_option_price(
            S, K, H, T, r, sigma,
            barrier_type="up_and_out",
            option_type=option_type,
            rebate=0.0,
            dividend_yield=q,
            method="closed_form",
        )["price"]
        return float(vanilla - out_price + rebate * np.exp(-r * T))

    return float("nan")  # unreachable


def _barrier_zero_vol(S, K, H, T, r, q, barrier_type, option_type, rebate):
    """Barrier price under zero volatility: deterministic path."""
    # Forward price
    F = S * np.exp((r - q) * T)
    disc = np.exp(-r * T)
    # Check if barrier is breached deterministically
    if "down" in barrier_type:
        breached = F <= H or S <= H
    else:
        breached = F >= H or S >= H

    if "out" in barrier_type:
        if breached:
            return float(rebate * disc)
        if option_type == "call":
            return float(max(F - K, 0.0) * disc)
        return float(max(K - F, 0.0) * disc)
    else:  # in
        if breached:
            if option_type == "call":
                return float(max(F - K, 0.0) * disc)
            return float(max(K - F, 0.0) * disc)
        return float(rebate * disc)


def barrier_option_price(
    spot: float,
    strike: float,
    barrier: float,
    time_to_expiry: float,
    risk_free_rate: float,
    volatility: float,
    *,
    barrier_type: Literal["up_and_in", "up_and_out", "down_and_in", "down_and_out"] = "up_and_out",
    option_type: Literal["call", "put"] = "call",
    rebate: float = 0.0,
    dividend_yield: float = 0.0,
    method: Literal["closed_form", "monte_carlo"] = "closed_form",
    n_simulations: int | None = None,
) -> dict[str, Any]:
    """Price a barrier option.

    Parameters
    ----------
    spot : float
        Current asset price (> 0).
    strike : float
        Strike price (> 0).
    barrier : float
        Barrier level (> 0).
    time_to_expiry : float
        Time to expiry in years (>= 0).
    risk_free_rate : float
        Continuously compounded risk-free rate.
    volatility : float
        Annual volatility (>= 0).
    barrier_type : {"up_and_in", "up_and_out", "down_and_in", "down_and_out"}
        Barrier type. Default "up_and_out".
    option_type : {"call", "put"}
        Default "call".
    rebate : float
        Rebate paid if knocked out. Default 0.0.
    dividend_yield : float
        Continuous dividend yield. Default 0.0.
    method : {"closed_form", "monte_carlo"}
        Pricing method. Default "closed_form".
    n_simulations : int or None
        Number of MC simulations (required for monte_carlo method).

    Returns
    -------
    dict with keys:
        price, method, barrier_type, and (MC only) barrier_breached_pct.

    Raises
    ------
    ValueError
        If inputs are invalid.

    References
    ----------
    Reiner & Rubinstein (1991). Risk Magazine, 4(8), 28-35.
    Haug (2007). The Complete Guide to Option Pricing Formulas.
    """
    if spot <= 0:
        raise ValueError(f"spot must be > 0, got {spot}")
    if strike <= 0:
        raise ValueError(f"strike must be > 0, got {strike}")
    if barrier <= 0:
        raise ValueError(f"barrier must be > 0, got {barrier}")
    if time_to_expiry < 0:
        raise ValueError(f"time_to_expiry must be >= 0, got {time_to_expiry}")
    if volatility < 0:
        raise ValueError(f"volatility must be >= 0, got {volatility}")
    if barrier_type not in ("up_and_in", "up_and_out", "down_and_in", "down_and_out"):
        raise ValueError(f"Invalid barrier_type: {barrier_type!r}")
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")
    if method not in ("closed_form", "monte_carlo"):
        raise ValueError(f"method must be 'closed_form' or 'monte_carlo', got {method!r}")

    S, K, H, T, r, sigma, q = spot, strike, barrier, time_to_expiry, risk_free_rate, volatility, dividend_yield

    if method == "closed_form":
        price = _barrier_cf(S, K, H, T, r, sigma, q, barrier_type, option_type, rebate)
        return {
            "price": float(max(price, 0.0)),
            "method": "closed_form",
            "barrier_type": barrier_type,
        }

    # Monte Carlo
    n_sims = n_simulations if n_simulations is not None else 10000
    if n_sims < 1:
        raise ValueError(f"n_simulations must be >= 1, got {n_sims}")

    n_steps = max(int(252 * T), 1)
    dt = T / n_steps
    drift = (r - q - 0.5 * sigma**2) * dt
    vol_sqrt_dt = sigma * np.sqrt(dt)

    rng = np.random.default_rng(None)
    Z = rng.standard_normal((n_sims, n_steps))
    log_inc = drift + vol_sqrt_dt * Z
    log_paths = np.cumsum(log_inc, axis=1)
    paths = S * np.exp(log_paths)  # (n_sims, n_steps)

    # Check barrier breach
    if "down" in barrier_type:
        breached = np.any(paths <= H, axis=1)  # (n_sims,)
    else:
        breached = np.any(paths >= H, axis=1)

    ST = paths[:, -1]
    disc = np.exp(-r * T)

    if option_type == "call":
        intrinsic = np.maximum(ST - K, 0.0)
    else:
        intrinsic = np.maximum(K - ST, 0.0)

    if "out" in barrier_type:
        payoffs = np.where(breached, rebate, intrinsic) * disc
    else:  # in
        payoffs = np.where(breached, intrinsic, rebate) * disc

    price_est = float(np.mean(payoffs))
    breached_pct = float(np.mean(breached))

    return {
        "price": float(max(price_est, 0.0)),
        "method": "monte_carlo",
        "barrier_type": barrier_type,
        "barrier_breached_pct": breached_pct,
    }


# ---------------------------------------------------------------------------
# Lookback option pricing
# ---------------------------------------------------------------------------

def _lookback_cf(
    S: float, K: float, T: float, r: float, sigma: float, q: float,
    option_type: str, strike_type: str,
) -> float:
    """Closed-form lookback using Goldman-Sosin-Gatto (1979) / Conze-Viswanathan (1991)."""
    if T <= 0:
        if strike_type == "floating":
            # At expiry, min = max = S; payoff = 0
            return 0.0
        if option_type == "call":
            return max(S - K, 0.0)
        return max(K - S, 0.0)

    if sigma <= 0:
        # Deterministic: S_T = S * exp((r-q)*T)
        ST = S * np.exp((r - q) * T)
        disc = np.exp(-r * T)
        if strike_type == "floating":
            if option_type == "call":
                return float(max(ST - S, 0.0) * disc)  # max(S_T - min, 0) ~ max(ST - S, 0)
            return float(max(S - ST, 0.0) * disc)
        if option_type == "call":
            return float(max(ST - K, 0.0) * disc)
        return float(max(K - ST, 0.0) * disc)

    sqrt_T = np.sqrt(T)
    disc_r = np.exp(-r * T)
    disc_q = np.exp(-q * T)
    b = r - q  # cost of carry

    def _phi(x: float) -> float:
        return float(norm.cdf(x))

    if strike_type == "floating":
        # Floating strike lookback
        # Call: E[e^{-rT} * (S_T - min_{0,T} S_t)]
        # Put:  E[e^{-rT} * (max_{0,T} S_t - S_T)]
        # Conze & Viswanathan (1991) formulas
        a1 = (np.log(S / S) + (b + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
        # Since m_0 = S (current price is the initial minimum/maximum)
        # Use simplified form with M_0 = m_0 = S
        a1_c = (b + 0.5 * sigma**2) * sqrt_T / sigma
        a2_c = a1_c - sigma * sqrt_T

        if option_type == "call":
            # Floating call = S*e^{-qT}*N(a1) - S*e^{-rT}*N(a2) + sigma^2/(2b) terms
            if abs(b) > 1e-8:
                term1 = S * disc_q * _phi(a1_c)
                term2 = S * disc_r * _phi(a2_c)
                term3 = (sigma**2 / (2.0 * b)) * S * (
                    disc_r * _phi(a2_c) - disc_q * (b * T + 1.0) * _phi(-a1_c)
                    # Actually use correct GSG formula:
                )
                # GSG (1979) floating call formula:
                # C_float = S*e^{-qT}*N(a1) - S*e^{-rT}*(sigma^2/(2b))*N(-a1)
                #         - S*e^{-rT}*N(a2) + S*e^{-rT}*(sigma^2/(2b))*N(-a2) [not exactly right]
                # Use Haug formulas directly:
                # d1 = (ln(S/m) + (b+σ²/2)T)/(σ√T), with m=S → d1 = (b+σ²/2)√T/σ
                d1 = (b + 0.5 * sigma**2) * sqrt_T / sigma
                d2 = d1 - sigma * sqrt_T
                price = (
                    S * disc_q * _phi(d1)
                    - S * disc_r * _phi(d2)
                    + S * disc_r * sigma**2 / (2.0 * b) * (
                        -_phi(-d1) * (S / S) ** (-2.0 * b / sigma**2)  # S/m = 1
                        + np.exp(0) * _phi(d2)
                    )
                )
                # Simplify with S/m = 1 → (S/m)^{-2b/σ²} = 1
                d1 = (b + 0.5 * sigma**2) * sqrt_T / sigma
                d2 = d1 - sigma * sqrt_T
                price = (
                    S * disc_q * _phi(d1)
                    - S * disc_r * _phi(d2)
                    + S * disc_r * (sigma**2 / (2.0 * b)) * (_phi(d2) - _phi(-d1))
                )
            else:
                # b ≈ 0: use limit
                d1 = 0.5 * sigma * sqrt_T
                d2 = -0.5 * sigma * sqrt_T
                price = (
                    S * _phi(d1) - S * disc_r * _phi(d2)
                    + S * disc_r * sigma * sqrt_T * norm.pdf(d1)
                )
            return float(max(price, 0.0))

        else:  # put
            if abs(b) > 1e-8:
                d1 = (b + 0.5 * sigma**2) * sqrt_T / sigma
                d2 = d1 - sigma * sqrt_T
                price = (
                    S * disc_r * _phi(-d2)
                    - S * disc_q * _phi(-d1)
                    + S * disc_r * (sigma**2 / (2.0 * b)) * (_phi(d2) - _phi(d1))
                )
            else:
                d1 = 0.5 * sigma * sqrt_T
                d2 = -0.5 * sigma * sqrt_T
                price = (
                    S * disc_r * _phi(d2) - S * _phi(-d1)
                    + S * disc_r * sigma * sqrt_T * norm.pdf(d1)
                )
            return float(max(price, 0.0))

    else:  # fixed strike
        # Fixed strike lookback call: E[e^{-rT} * max(max_{0,T} S_t - K, 0)]
        # Fixed strike lookback put:  E[e^{-rT} * max(K - min_{0,T} S_t, 0)]
        if option_type == "call":
            # Conze & Viswanathan (1991) fixed call:
            # Uses max M_0 = S (current price is initial running max)
            M0 = S
            if M0 > K:
                # Already in-the-money for the running max
                d1 = (np.log(M0 / K) + (b + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
                d2 = d1 - sigma * sqrt_T
                a1 = (np.log(M0 / S) + (b + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
                a2 = a1 - sigma * sqrt_T
                if abs(b) > 1e-8:
                    part1 = S * disc_q * _phi(a1) - K * disc_r * _phi(a2)
                    part2 = (sigma**2 / (2.0 * b)) * S * disc_q * (
                        -(M0 / S) ** (-2.0 * b / sigma**2) * _phi(-a1)
                        + np.exp(b * T) * _phi(a1 - sigma * sqrt_T * (2.0 * b / sigma**2 + 1.0))
                    )
                    price = part1 + part2
                else:
                    price = S * disc_q * _phi(a1) - K * disc_r * _phi(a2)
            else:
                # Standard formula
                d1 = (np.log(S / K) + (b + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
                d2 = d1 - sigma * sqrt_T
                if abs(b) > 1e-8:
                    price = (
                        S * disc_q * _phi(d1)
                        - K * disc_r * _phi(d2)
                        + S * disc_r * (sigma**2 / (2.0 * b)) * (
                            -(S / K) ** (-2.0 * b / sigma**2) * _phi(-d1 + 2.0 * b * sqrt_T / sigma)
                            + np.exp(b * T) * _phi(d1)
                        )
                    )
                else:
                    price = (
                        S * disc_q * _phi(d1)
                        - K * disc_r * _phi(d2)
                        + S * disc_r * sigma * sqrt_T * norm.pdf(d1)
                    )
            return float(max(price, 0.0))

        else:  # put
            m0 = S  # current running minimum
            if m0 < K:
                d1 = (np.log(m0 / K) + (b + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
                d2 = d1 - sigma * sqrt_T
                a1 = (np.log(S / m0) - (b + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
                a2 = a1 + sigma * sqrt_T
                if abs(b) > 1e-8:
                    part1 = K * disc_r * _phi(-d2) - m0 * disc_q * _phi(-d1)
                    price = part1
                else:
                    price = K * disc_r * _phi(-d2) - m0 * disc_q * _phi(-d1)
            else:
                # K <= m0: fixed put, standard formula
                d1 = (np.log(S / K) + (b + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
                d2 = d1 - sigma * sqrt_T
                if abs(b) > 1e-8:
                    price = (
                        K * disc_r * _phi(-d2)
                        - S * disc_q * _phi(-d1)
                        + S * disc_r * (sigma**2 / (2.0 * b)) * (
                            (S / K) ** (-2.0 * b / sigma**2) * _phi(d1 - 2.0 * b * sqrt_T / sigma)
                            - np.exp(b * T) * _phi(-d1)
                        )
                    )
                else:
                    price = (
                        K * disc_r * _phi(-d2)
                        - S * disc_q * _phi(-d1)
                        + S * disc_r * sigma * sqrt_T * norm.pdf(d1)
                    )
            return float(max(price, 0.0))


def lookback_option_price(
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    volatility: float,
    *,
    option_type: Literal["call", "put"] = "call",
    strike_type: Literal["fixed", "floating"] = "floating",
    dividend_yield: float = 0.0,
    method: Literal["closed_form", "monte_carlo"] = "closed_form",
    n_simulations: int | None = None,
) -> dict[str, Any]:
    """Price a lookback option.

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
    option_type : {"call", "put"}
        Default "call".
    strike_type : {"fixed", "floating"}
        Floating: payoff uses path min/max as effective strike.
        Fixed: payoff uses path max/min vs fixed K.
    dividend_yield : float
        Continuous dividend yield. Default 0.0.
    method : {"closed_form", "monte_carlo"}
        Pricing method. Default "closed_form".
    n_simulations : int or None
        MC simulations (for monte_carlo method).

    Returns
    -------
    dict with keys: price, method, strike_type.

    Raises
    ------
    ValueError
        If inputs are invalid.

    References
    ----------
    Goldman, Sosin & Gatto (1979). Journal of Finance, 34(5), 1111-1127.
    Haug (2007). The Complete Guide to Option Pricing Formulas.
    """
    if spot <= 0:
        raise ValueError(f"spot must be > 0, got {spot}")
    if strike <= 0:
        raise ValueError(f"strike must be > 0, got {strike}")
    if time_to_expiry < 0:
        raise ValueError(f"time_to_expiry must be >= 0, got {time_to_expiry}")
    if volatility < 0:
        raise ValueError(f"volatility must be >= 0, got {volatility}")
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")
    if strike_type not in ("fixed", "floating"):
        raise ValueError(f"strike_type must be 'fixed' or 'floating', got {strike_type!r}")
    if method not in ("closed_form", "monte_carlo"):
        raise ValueError(f"method must be 'closed_form' or 'monte_carlo', got {method!r}")

    S, K, T, r, sigma, q = spot, strike, time_to_expiry, risk_free_rate, volatility, dividend_yield

    if method == "closed_form":
        price = _lookback_cf(S, K, T, r, sigma, q, option_type, strike_type)
        return {
            "price": float(price),
            "method": "closed_form",
            "strike_type": strike_type,
        }

    # Monte Carlo
    n_sims = n_simulations if n_simulations is not None else 10000
    if n_sims < 1:
        raise ValueError(f"n_simulations must be >= 1, got {n_sims}")

    n_steps = max(int(252 * T), 1)
    dt = T / n_steps
    drift = (r - q - 0.5 * sigma**2) * dt
    vol_sqrt_dt = sigma * np.sqrt(dt)

    rng = np.random.default_rng(None)
    Z = rng.standard_normal((n_sims, n_steps))
    log_inc = drift + vol_sqrt_dt * Z
    log_paths = np.cumsum(log_inc, axis=1)
    paths = S * np.exp(log_paths)  # (n_sims, n_steps)

    ST = paths[:, -1]
    path_max = np.max(paths, axis=1)
    path_min = np.min(paths, axis=1)

    disc = np.exp(-r * T)

    if strike_type == "floating":
        if option_type == "call":
            payoffs = disc * np.maximum(ST - path_min, 0.0)
        else:
            payoffs = disc * np.maximum(path_max - ST, 0.0)
    else:  # fixed
        if option_type == "call":
            payoffs = disc * np.maximum(path_max - K, 0.0)
        else:
            payoffs = disc * np.maximum(K - path_min, 0.0)

    price_est = float(np.mean(payoffs))

    return {
        "price": float(max(price_est, 0.0)),
        "method": "monte_carlo",
        "strike_type": strike_type,
    }
