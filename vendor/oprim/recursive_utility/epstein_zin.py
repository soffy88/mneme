"""Epstein-Zin recursive utility aggregator (Epstein-Zin 1989, Kreps-Porteus 1978)."""

from __future__ import annotations

import numpy as np

_LOG_SPACE_RHO_THRESHOLD = -50.0  # use log-space for numerical stability below this


def epstein_zin_aggregator(
    consumption: np.ndarray,
    continuation_value: np.ndarray,
    *,
    discount: float,
    risk_aversion: float,
    ies: float,
) -> np.ndarray:
    """Epstein-Zin recursive utility aggregator.

    Aggregates current consumption ``C_t`` and continuation certainty equivalent
    ``CE_t`` into the period utility value ``V_t``.

    Mathematical definition (Epstein-Zin 1989 / Kreps-Porteus 1978):

        rho  = 1 - 1/psi            (psi = ies)
        V_t  = ((1-beta)*C^rho + beta*CE^rho)^(1/rho)   for rho != 0
        V_t  = C^(1-beta) * CE^beta                      for rho = 0  (ies = 1)

    where ``continuation_value`` is the certainty equivalent
    ``CE = E[V_{t+1}^(1-gamma)]^(1/(1-gamma))``, which must be pre-computed by
    the caller.

    When ``|rho|`` is large (``ies`` near 0), the computation is performed in
    log-space for numerical stability:

        log_inner = log((1-beta)*exp(rho*log_C) + beta*exp(rho*log_CE))
        log_V     = log_inner / rho

    Parameters
    ----------
    consumption : np.ndarray
        Current consumption ``C_t``. All values must be strictly positive.
    continuation_value : np.ndarray
        Certainty equivalent ``CE_t`` of continuation, same shape as
        ``consumption``. All values must be strictly positive.
    discount : float
        Discount factor ``beta``. Must satisfy 0 < beta < 1.
    risk_aversion : float
        Coefficient of relative risk aversion ``gamma``. Must be > 0.
    ies : float
        Intertemporal elasticity of substitution ``psi``. Must be > 0.

    Returns
    -------
    np.ndarray
        Period utility values ``V_t``, same shape as inputs.

    Raises
    ------
    ValueError
        If parameter constraints are violated or any input values are non-positive.

    References
    ----------
    Epstein, L. G. and Zin, S. E. (1989). Substitution, risk aversion, and the
    temporal behavior of consumption and asset returns: A theoretical framework.
    *Econometrica*, 57(4), 937-969.

    Kreps, D. M. and Porteus, E. L. (1978). Temporal resolution of uncertainty
    and dynamic choice theory. *Econometrica*, 46(1), 185-200.
    """
    # --- parameter validation ---
    if not (0.0 < discount < 1.0):
        raise ValueError(f"discount must be in (0, 1), got {discount!r}")
    if risk_aversion <= 0.0:
        raise ValueError(f"risk_aversion must be > 0, got {risk_aversion!r}")
    if ies <= 0.0:
        raise ValueError(f"ies must be > 0, got {ies!r}")

    c = np.asarray(consumption, dtype=float)
    ce = np.asarray(continuation_value, dtype=float)

    if np.any(c <= 0.0):
        raise ValueError("All consumption values must be strictly positive (> 0).")
    if np.any(ce <= 0.0):
        raise ValueError("All continuation_value entries must be strictly positive (> 0).")

    beta = discount
    rho = 1.0 - 1.0 / ies  # = 1 - 1/psi

    # --- special case: ies = 1 → rho = 0 → Cobb-Douglas ---
    if abs(rho) < 1e-12:
        return c ** (1.0 - beta) * ce**beta

    # --- general case ---
    w1 = 1.0 - beta
    w2 = beta

    if rho < _LOG_SPACE_RHO_THRESHOLD:
        # log-space for extreme negative rho (near-zero ies)
        log_c = np.log(c)
        log_ce = np.log(ce)
        # inner = w1*exp(rho*log_c) + w2*exp(rho*log_ce)
        # Use logsumexp-style for stability: factor out max term
        a = rho * log_c
        b = rho * log_ce
        mx = np.maximum(a, b)
        log_inner = mx + np.log(w1 * np.exp(a - mx) + w2 * np.exp(b - mx))
        return np.exp(log_inner / rho)

    inner = w1 * c**rho + w2 * ce**rho
    # inner should be positive since c, ce > 0 and w1, w2 > 0
    return inner ** (1.0 / rho)
