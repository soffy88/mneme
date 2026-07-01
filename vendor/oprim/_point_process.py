"""Point process atomic operations."""

from __future__ import annotations

import numpy as np


def hawkes_nll(
    params: np.ndarray,
    event_times: np.ndarray,
    T: float,
) -> float:
    """Negative log-likelihood of exponential Hawkes process.

    Model: λ(t) = μ + Σ_{t_i < t} α·exp(-β·(t - t_i))

    Uses log-parameterization: params = [log_μ, log_α, log_β]
    for positivity constraint.

    Parameters
    ----------
    params : np.ndarray
        [log_mu, log_alpha, log_beta].
    event_times : np.ndarray
        Sorted 1-D array of event times.
    T : float
        Observation window end time.

    Returns
    -------
    float
        Negative log-likelihood (lower = better fit).

    References
    ----------
    .. [1] Hawkes, A.G. (1971). Spectra of some self-exciting and mutually exciting point processes.
    .. [2] Ogata, Y. (1981). On Lewis' simulation method for point processes.
    .. [3] Extraction source: Selene project, sel_v2/hawkes/mle.py:hawkes_nll
    """
    log_mu, log_alpha, log_beta = params
    mu = np.exp(log_mu)
    alpha = np.exp(log_alpha)
    beta = np.exp(log_beta)

    n = len(event_times)
    if n < 2:
        return 1e10

    # Recursive A_i = Σ_{j<i} exp(-β*(t_i - t_j))
    A = np.zeros(n)
    for i in range(1, n):
        A[i] = np.exp(-beta * (event_times[i] - event_times[i - 1])) * (1.0 + A[i - 1])

    lambdas = mu + alpha * A
    if np.any(lambdas <= 0):
        return 1e10

    log_sum = np.sum(np.log(lambdas))
    integral = mu * T + (alpha / beta) * np.sum(1.0 - np.exp(-beta * (T - event_times)))
    nll = -(log_sum - integral)
    return float(nll) if np.isfinite(nll) else 1e10
