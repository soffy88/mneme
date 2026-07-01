"""Longstaff-Schwartz LSM algorithm for American option pricing.

References
----------
Longstaff, F.A. & Schwartz, E.S. (2001). Valuing American Options by
    Simulation: A Simple Least-Squares Approach. Review of Financial
    Studies, 14(1), 113-147.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np


def _basis_matrix(x: np.ndarray, n_basis: int, kind: str) -> np.ndarray:
    """Build basis function matrix for regression.

    Parameters
    ----------
    x : np.ndarray, shape (n,)
        In-the-money spot values.
    n_basis : int
        Number of basis functions.
    kind : {"polynomial", "laguerre", "hermite"}
        Basis type.

    Returns
    -------
    np.ndarray, shape (n, n_basis)
    """
    if kind == "polynomial":
        cols = [x**i for i in range(n_basis)]
    elif kind == "laguerre":
        # Laguerre polynomials: L_0=1, L_1=1-x, L_2=1-2x+x^2/2, ...
        cols = []
        for i in range(n_basis):
            if i == 0:
                cols.append(np.ones_like(x))
            elif i == 1:
                cols.append(1.0 - x)
            elif i == 2:
                cols.append(1.0 - 2.0 * x + 0.5 * x**2)
            elif i == 3:
                cols.append(1.0 - 3.0 * x + 1.5 * x**2 - x**3 / 6.0)
            else:
                # Fall back to polynomial for higher orders
                cols.append(x**i)
    elif kind == "hermite":
        # Physicists' Hermite polynomials: H_0=1, H_1=2x, H_2=4x^2-2, ...
        cols = []
        for i in range(n_basis):
            if i == 0:
                cols.append(np.ones_like(x))
            elif i == 1:
                cols.append(2.0 * x)
            elif i == 2:
                cols.append(4.0 * x**2 - 2.0)
            elif i == 3:
                cols.append(8.0 * x**3 - 12.0 * x)
            else:
                cols.append(x**i)
    else:
        raise ValueError(f"Unknown basis_functions: {kind!r}")

    return np.column_stack(cols)


def lsm_american_price(
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    volatility: float,
    *,
    n_simulations: int = 10000,
    n_time_steps: int = 50,
    option_type: Literal["call", "put"] = "put",
    basis_functions: Literal["polynomial", "laguerre", "hermite"] = "polynomial",
    n_basis: int = 3,
    dividend_yield: float = 0.0,
    seed: int | None = None,
) -> dict[str, Any]:
    """Price an American option using the Longstaff-Schwartz LSM algorithm.

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
    n_time_steps : int
        Number of time steps. Default 50.
    option_type : {"call", "put"}
        Default "put".
    basis_functions : {"polynomial", "laguerre", "hermite"}
        Basis for regression. Default "polynomial".
    n_basis : int
        Number of basis functions. Default 3.
    dividend_yield : float
        Continuous dividend yield. Default 0.0.
    seed : int or None
        Random seed.

    Returns
    -------
    dict with keys:
        price, standard_error, exercise_boundary, early_exercise_frequency.

    Raises
    ------
    ValueError
        If inputs are invalid.

    References
    ----------
    Longstaff & Schwartz (2001). Review of Financial Studies, 14(1), 113-147.
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
    if n_time_steps < 1:
        raise ValueError(f"n_time_steps must be >= 1, got {n_time_steps}")
    if n_basis < 1:
        raise ValueError(f"n_basis must be >= 1, got {n_basis}")
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")
    if basis_functions not in ("polynomial", "laguerre", "hermite"):
        raise ValueError("basis_functions must be 'polynomial', 'laguerre', or 'hermite'")

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
            "exercise_boundary": [],
            "early_exercise_frequency": 1.0 if price > 0 else 0.0,
        }

    rng = np.random.default_rng(seed)
    dt = T / n_time_steps
    disc = np.exp(-r * dt)
    drift = (r - q - 0.5 * sigma**2) * dt
    vol_sqrt_dt = sigma * np.sqrt(dt)

    # Simulate paths: shape (n_simulations, n_time_steps + 1)
    Z = rng.standard_normal((n_simulations, n_time_steps))
    log_inc = drift + vol_sqrt_dt * Z
    log_paths = np.zeros((n_simulations, n_time_steps + 1))
    log_paths[:, 0] = np.log(S)
    log_paths[:, 1:] = np.log(S) + np.cumsum(log_inc, axis=1)
    paths = np.exp(log_paths)  # (n_sims, n_steps+1)

    def _payoff(s: np.ndarray) -> np.ndarray:
        if option_type == "call":
            return np.maximum(s - K, 0.0)
        return np.maximum(K - s, 0.0)

    # Terminal payoffs (step n_time_steps)
    cash_flows = _payoff(paths[:, -1])

    # Track exercise decisions for boundary and frequency
    # exercise_time[i] = time step at which path i exercises (n_time_steps = hold to expiry)
    exercise_time = np.full(n_simulations, n_time_steps, dtype=int)
    exercise_boundary: list[float] = []
    n_early_exercises = 0

    # Backward induction from T-1 down to step 1
    for t in range(n_time_steps - 1, 0, -1):
        St = paths[:, t]
        intrinsic = _payoff(St)

        # Only consider in-the-money paths for regression
        itm = intrinsic > 0
        n_itm = int(np.sum(itm))

        if n_itm < n_basis:
            # Too few ITM paths: skip regression, no early exercise at this step
            exercise_boundary.append(float("nan"))
            # Discount existing cash flows
            cash_flows = cash_flows * disc
            continue

        # Discounted continuation values for ITM paths
        # cash_flows currently holds payoff at exercise_time[i] discounted to step t+1
        # We need to discount one more step
        disc_factor = np.exp(-r * (exercise_time - t) * dt)
        continuation = cash_flows * disc_factor  # discounted from exercise time to t

        X = St[itm]
        Y = continuation[itm]

        # Normalise X for numerical stability
        X_mean = np.mean(X)
        X_std = np.std(X) if np.std(X) > 1e-10 else 1.0
        X_norm = (X - X_mean) / X_std

        try:
            A = _basis_matrix(X_norm, n_basis, basis_functions)
            # OLS: min ||A*beta - Y||^2
            coeffs, _, _, _ = np.linalg.lstsq(A, Y, rcond=None)
            continuation_hat = A @ coeffs
        except (np.linalg.LinAlgError, ValueError):
            exercise_boundary.append(float("nan"))
            cash_flows = cash_flows * disc
            continue

        # Exercise decision for ITM paths
        exercise = intrinsic[itm] > continuation_hat
        itm_indices = np.where(itm)[0]

        # Record boundary: threshold S at which we're indifferent (interpolation)
        if np.any(exercise):
            boundary_candidates = X[exercise]
            if option_type == "put":
                boundary = float(np.max(boundary_candidates))
            else:
                boundary = float(np.min(boundary_candidates))
        else:
            boundary = float("nan")
        exercise_boundary.append(boundary)

        # Update cash flows for paths that exercise
        exercise_paths = itm_indices[exercise]
        if len(exercise_paths) > 0:
            cash_flows[exercise_paths] = intrinsic[itm_indices][exercise]
            exercise_time[exercise_paths] = t

    # At step 0 (t=0), we do not exercise (it's the current time)
    # Final price: discount each path's cash flow from exercise_time to t=0
    disc_factors = np.exp(-r * exercise_time * dt)
    discounted_payoffs = cash_flows * disc_factors

    price_est = float(np.mean(discounted_payoffs))
    se = float(np.std(discounted_payoffs, ddof=1) / np.sqrt(n_simulations))

    # Early exercise frequency: fraction of paths exercised before expiry
    early_ex_freq = float(np.mean(exercise_time < n_time_steps))

    # Reverse boundary (we built it backwards)
    exercise_boundary.reverse()

    return {
        "price": float(max(price_est, 0.0)),
        "standard_error": se,
        "exercise_boundary": exercise_boundary,
        "early_exercise_frequency": early_ex_freq,
    }
