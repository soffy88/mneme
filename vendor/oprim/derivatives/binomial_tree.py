"""Binomial tree option pricing (CRR and Jarrow-Rudd).

References
----------
Cox, J.C., Ross, S.A. & Rubinstein, M. (1979). Option Pricing: A Simplified
    Approach. Journal of Financial Economics, 7(3), 229-263.
Jarrow, R. & Rudd, A. (1983). Option Pricing. Irwin, Homewood, Illinois.
"""
from __future__ import annotations

from typing import Any, Literal

import numpy as np


def binomial_tree_price(
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float,
    volatility: float,
    *,
    n_steps: int = 100,
    option_type: Literal["call", "put"] = "call",
    exercise: Literal["european", "american"] = "european",
    method: Literal["crr", "jarrow_rudd"] = "crr",
    dividend_yield: float = 0.0,
) -> dict[str, Any]:
    """Price an option using a binomial tree.

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
    n_steps : int
        Number of time steps (>= 1). Default 100.
    option_type : {"call", "put"}
        Option type. Default "call".
    exercise : {"european", "american"}
        Exercise style. Default "european".
    method : {"crr", "jarrow_rudd"}
        Tree parameterisation. Default "crr".
    dividend_yield : float
        Continuous dividend yield. Default 0.0.

    Returns
    -------
    dict with keys:
        price, method, n_steps, and (american only) early_exercise_boundary.

    Raises
    ------
    ValueError
        If inputs are invalid.

    References
    ----------
    Cox, Ross & Rubinstein (1979). Journal of Financial Economics, 7(3), 229-263.
    """
    if spot <= 0:
        raise ValueError(f"spot must be > 0, got {spot}")
    if strike <= 0:
        raise ValueError(f"strike must be > 0, got {strike}")
    if time_to_expiry < 0:
        raise ValueError(f"time_to_expiry must be >= 0, got {time_to_expiry}")
    if n_steps < 1:
        raise ValueError(f"n_steps must be >= 1, got {n_steps}")
    if volatility < 0:
        raise ValueError(f"volatility must be >= 0, got {volatility}")
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")
    if exercise not in ("european", "american"):
        raise ValueError(f"exercise must be 'european' or 'american', got {exercise!r}")
    if method not in ("crr", "jarrow_rudd"):
        raise ValueError(f"method must be 'crr' or 'jarrow_rudd', got {method!r}")

    S, K, T, r, sigma, q = spot, strike, time_to_expiry, risk_free_rate, volatility, dividend_yield

    # Edge case: expiry at time 0
    if T == 0:
        if option_type == "call":
            price = float(max(S - K, 0.0))
        else:
            price = float(max(K - S, 0.0))
        result: dict[str, Any] = {"price": price, "method": method, "n_steps": n_steps}
        if exercise == "american":
            result["early_exercise_boundary"] = []
        return result

    dt = T / n_steps
    discount = np.exp(-r * dt)

    # Tree parameters
    if method == "crr":
        if sigma == 0:
            u = np.exp(r * dt)
            d = np.exp(-r * dt)
        else:
            u = np.exp(sigma * np.sqrt(dt))
            d = 1.0 / u
        denom = u - d
        if abs(denom) < 1e-12:
            p = 0.5
        else:
            p = (np.exp((r - q) * dt) - d) / denom
    else:  # jarrow_rudd
        drift = (r - q - 0.5 * sigma**2) * dt
        if sigma == 0:
            u = np.exp(drift)
            d = np.exp(drift)
        else:
            u = np.exp(drift + sigma * np.sqrt(dt))
            d = np.exp(drift - sigma * np.sqrt(dt))
        # Risk-neutral probability for JR is 0.5 by construction
        p = 0.5

    # Clamp risk-neutral probability
    p = float(np.clip(p, 0.0, 1.0))
    q_prob = 1.0 - p

    # Build terminal asset prices (vectorised)
    j = np.arange(n_steps + 1, dtype=float)
    ST = S * (u ** (n_steps - j)) * (d**j)

    # Terminal payoffs
    if option_type == "call":
        payoffs = np.maximum(ST - K, 0.0)
    else:
        payoffs = np.maximum(K - ST, 0.0)

    # Track early exercise boundary (critical spot at each time step, american only)
    early_exercise_boundary: list[float] = []

    # Backward induction
    V = payoffs.copy()
    for step in range(n_steps - 1, -1, -1):
        # Continuation value
        V = discount * (p * V[:-1] + q_prob * V[1:])

        if exercise == "american":
            # Spot prices at this node
            j_nodes = np.arange(step + 1, dtype=float)
            S_nodes = S * (u ** (step - j_nodes)) * (d**j_nodes)
            if option_type == "call":
                intrinsic = np.maximum(S_nodes - K, 0.0)
            else:
                intrinsic = np.maximum(K - S_nodes, 0.0)
            # Exercise decision
            exercise_mask = intrinsic > V
            V = np.where(exercise_mask, intrinsic, V)

            # Record the critical spot (lowest spot where early exercise is optimal)
            if np.any(exercise_mask):
                # For puts: lowest S_node where exercise; for calls: highest
                if option_type == "put":
                    boundary = float(np.max(S_nodes[exercise_mask]))
                else:
                    boundary = float(np.min(S_nodes[exercise_mask]))
                early_exercise_boundary.append(boundary)
            else:
                early_exercise_boundary.append(float("nan"))

    result = {
        "price": float(V[0]),
        "method": method,
        "n_steps": n_steps,
    }
    if exercise == "american":
        # Reverse to go from time 0 forward
        early_exercise_boundary.reverse()
        result["early_exercise_boundary"] = early_exercise_boundary

    return result
