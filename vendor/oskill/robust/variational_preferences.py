"""Variational preferences for robust portfolio optimization.

References
----------
Maccheroni, F., Marinacci, M. & Rustichini, A. (2006).
    Ambiguity aversion, robustness, and the variational representation of preferences.
    Econometrica, 74(6), 1447-1498.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
from scipy.optimize import minimize


def _utility_values(
    returns_portfolio: np.ndarray, utility: str, risk_aversion: float
) -> np.ndarray:
    """Compute per-period utility values."""
    r = returns_portfolio
    if utility == "log":
        return np.log(np.maximum(1.0 + r, 1e-10))
    elif utility == "power":
        gamma = risk_aversion
        if abs(gamma - 1.0) < 1e-8:
            return np.log(np.maximum(1.0 + r, 1e-10))
        return ((1.0 + r) ** (1.0 - gamma) - 1.0) / (1.0 - gamma)
    else:
        raise ValueError(f"Unknown utility: {utility!r}")


def _optimal_measure(
    u: np.ndarray,
    cost_function: Literal["entropy", "chi_square", "wasserstein"],
    ambiguity_index: float,
) -> tuple[np.ndarray, float]:
    """Compute optimal probability distortion Q* and its divergence cost."""
    T = len(u)
    eps = 1e-12

    if cost_function == "entropy":
        # Q_t* ∝ exp(-u_t / ambiguity_index)
        log_q = -u / ambiguity_index
        log_q -= log_q.max()
        q = np.exp(log_q)
        q = q / q.sum()
        # KL divergence: ambiguity_index * sum_t q_t * log(q_t * T)
        kl = float(np.sum(q * np.log(q * T + eps)))
        cost = ambiguity_index * kl

    elif cost_function == "chi_square":
        # Q_t* ∝ max(0, 1 - u_t / (2 * ambiguity_index))
        q = np.maximum(0.0, 1.0 - u / (2.0 * ambiguity_index))
        q_sum = q.sum()
        if q_sum < eps:
            q = np.ones(T) / T
        else:
            q = q / q_sum
        # Chi-square divergence cost: ambiguity_index * sum_t T*(q_t - 1/T)^2
        chi2 = float(T * np.sum((q - 1.0 / T) ** 2))
        cost = ambiguity_index * chi2

    elif cost_function == "wasserstein":
        # Shift probability mass toward lowest utility outcomes
        sort_idx = np.argsort(u)  # ascending: worst first
        q = np.ones(T) / T
        # Transfer mass proportional to 1/ambiguity_index to worst outcomes
        shift = min(0.5, 1.0 / (ambiguity_index + eps))
        extra = shift / T
        for i in range(T // 4):  # shift from best to worst quartile
            src = sort_idx[T - 1 - i]
            dst = sort_idx[i]
            transfer = min(q[src], extra)
            q[src] -= transfer
            q[dst] += transfer
        q = np.maximum(q, 0.0)
        q = q / q.sum()
        # Wasserstein cost approximation: ambiguity_index * L1 distance
        cost = float(ambiguity_index * np.sum(np.abs(q - 1.0 / T)))

    else:
        raise ValueError(f"Unknown cost_function: {cost_function!r}")

    return q, max(0.0, cost)


def _variational_value(
    w: np.ndarray,
    returns: np.ndarray,
    cost_function: Literal["entropy", "chi_square", "wasserstein"],
    ambiguity_index: float,
    utility: str,
    risk_aversion: float,
) -> tuple[float, np.ndarray, float]:
    """Compute variational value V(f(w)) = E_Q[u] + c(Q) minimized over Q."""
    r_portfolio = returns @ w
    u = _utility_values(r_portfolio, utility, risk_aversion)
    q, cost = _optimal_measure(u, cost_function, ambiguity_index)
    v = float(np.dot(q, u)) + cost
    return v, q, cost


def variational_preferences_estimate(
    reference_returns: np.ndarray,
    *,
    cost_function: Literal["entropy", "chi_square", "wasserstein"] = "entropy",
    ambiguity_index: float = 1.0,
    utility: Literal["log", "power"] = "log",
    risk_aversion: float = 2.0,
) -> dict[str, Any]:
    """Robust portfolio via variational (MMR) preferences.

    Solves: max_w V(f(w)) = max_w min_Q { E_Q[u(f(w))] + c(Q) }

    Parameters
    ----------
    reference_returns : np.ndarray
        Returns matrix of shape (T, N).
    cost_function : {"entropy", "chi_square", "wasserstein"}
        Divergence cost penalizing deviations from reference measure.
    ambiguity_index : float
        Ambiguity aversion parameter (>= 0).
        Large value → near expected utility.
    utility : {"log", "power"}
        Utility function specification.
    risk_aversion : float
        Risk aversion for power utility.

    Returns
    -------
    dict with keys:
        ``weights`` — portfolio weights, shape (N,).
        ``worst_measure_q`` — optimal distorted probability, shape (T,).
        ``cost_at_optimum`` — divergence cost at optimal Q.
        ``divergence_type_used`` — cost_function used.
    """
    returns = np.asarray(reference_returns, dtype=float)
    if returns.ndim == 1:
        returns = returns.reshape(-1, 1)
    T, N = returns.shape

    def neg_variational(w: np.ndarray) -> float:
        v, _, _ = _variational_value(
            w, returns, cost_function, ambiguity_index, utility, risk_aversion
        )
        return -v

    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    bounds = [(0.0, 1.0)] * N
    w0 = np.ones(N) / N

    result = minimize(
        neg_variational,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 500, "ftol": 1e-8},
    )
    w_opt = result.x
    w_opt = np.maximum(w_opt, 0.0)
    w_opt = w_opt / w_opt.sum()

    _, q_star, cost_opt = _variational_value(
        w_opt, returns, cost_function, ambiguity_index, utility, risk_aversion
    )

    return {
        "weights": w_opt,
        "worst_measure_q": q_star,
        "cost_at_optimum": float(cost_opt),
        "divergence_type_used": cost_function,
    }
