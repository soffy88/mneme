"""Hansen-Sargent multiplier preferences for robust portfolio optimization.

References
----------
Hansen, L.P. & Sargent, T.J. (2001). Robust control and model uncertainty.
    American Economic Review, 91(2), 60-66.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
from scipy.optimize import minimize


def _utility(returns_portfolio: np.ndarray, utility: str, risk_aversion: float) -> np.ndarray:
    """Compute per-period utility values."""
    r = returns_portfolio
    if utility == "log":
        return np.log(np.maximum(1.0 + r, 1e-10))
    elif utility == "power":
        gamma = risk_aversion
        if abs(gamma - 1.0) < 1e-8:
            return np.log(np.maximum(1.0 + r, 1e-10))
        return ((1.0 + r) ** (1.0 - gamma) - 1.0) / (1.0 - gamma)
    elif utility == "exponential":
        return -np.exp(-risk_aversion * r) / risk_aversion
    else:
        raise ValueError(f"Unknown utility: {utility!r}")


def _worst_case_utility(
    w: np.ndarray, returns: np.ndarray, theta: float, utility_fn: str, risk_aversion: float
) -> float:
    """Compute worst-case utility under optimal exponential tilting."""
    r_portfolio = returns @ w
    u = _utility(r_portfolio, utility_fn, risk_aversion)
    # Optimal distortion: m_t* ∝ exp(-u_t / theta)
    log_m = -u / theta
    log_m -= log_m.max()  # numerical stability
    m = np.exp(log_m)
    m = m / m.sum()
    return float(np.dot(m, u))


def multiplier_preferences_robust(
    reference_model_returns: np.ndarray,
    *,
    theta: float,
    utility: Literal["log", "power", "exponential"] = "log",
    risk_aversion: float = 2.0,
    n_perturbations: int = 100,
    perturbation_seed: int = 42,
) -> dict[str, Any]:
    """Robust portfolio optimization via Hansen-Sargent multiplier preferences.

    Solves: max_w min_m { sum_t m_t * u(R(w)_t) + theta * sum_t m_t * log(m_t) }
    where the optimal m_t* uses exponential tilting.

    Parameters
    ----------
    reference_model_returns : np.ndarray
        Returns matrix of shape (T, N).
    theta : float
        Penalty parameter controlling model uncertainty (> 0).
        Large theta → near expected utility; small theta → high robustness.
    utility : {"log", "power", "exponential"}
        Utility function specification.
    risk_aversion : float
        Risk aversion parameter for power/exponential utility.
    n_perturbations : int
        Number of perturbations for detection error probability estimation.
    perturbation_seed : int
        Random seed for perturbations.

    Returns
    -------
    dict with keys:
        ``weights`` — robust portfolio weights, shape (N,).
        ``worst_case_distortion`` — optimal m_t* - 1/T, shape (T,).
        ``detection_error_prob`` — detection error probability (simplified).
        ``theta_effective`` — theta value used.
    """
    if theta <= 0:
        raise ValueError(f"theta must be > 0, got {theta}")

    returns = np.asarray(reference_model_returns, dtype=float)
    if returns.ndim == 1:
        returns = returns.reshape(-1, 1)
    T, N = returns.shape

    def neg_worst_case(w: np.ndarray) -> float:
        return -_worst_case_utility(w, returns, theta, utility, risk_aversion)

    # SLSQP with sum(w) = 1 constraint
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    bounds = [(0.0, 1.0)] * N
    w0 = np.ones(N) / N

    result = minimize(
        neg_worst_case,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 500, "ftol": 1e-8},
    )
    w_opt = result.x
    w_opt = np.maximum(w_opt, 0.0)
    w_opt = w_opt / w_opt.sum()

    # Compute worst-case distortion at optimum
    r_portfolio = returns @ w_opt
    u = _utility(r_portfolio, utility, risk_aversion)
    log_m = -u / theta
    log_m -= log_m.max()
    m_star = np.exp(log_m)
    m_star = m_star / m_star.sum()
    distortion = m_star - 1.0 / T

    # Detection error probability (simplified formula)
    dep = float(0.5 * (1.0 - 0.5 * np.sum(np.abs(m_star - 1.0 / T))))
    dep = float(np.clip(dep, 0.0, 0.5))

    return {
        "weights": w_opt,
        "worst_case_distortion": distortion,
        "detection_error_prob": dep,
        "theta_effective": float(theta),
    }
