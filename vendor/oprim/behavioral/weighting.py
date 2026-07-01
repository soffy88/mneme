"""Probability weighting functions (CPT / rank-dependent utility)."""

from __future__ import annotations

import warnings
from typing import Literal

import numpy as np


def probability_weighting_function(
    p: np.ndarray | float,
    *,
    form: Literal["tk", "prelec"] = "tk",
    gamma_gain: float = 0.61,
    gamma_loss: float = 0.69,
    delta: float = 1.0,
    side: Literal["gain", "loss"] = "gain",
) -> np.ndarray | float:
    """Probability weighting function from CPT.

    Tversky-Kahneman (TK) form:
        w(p) = p^gamma / (p^gamma + (1-p)^gamma)^(1/gamma)

    Prelec one-parameter form:
        w(p) = exp(-delta * (-ln p)^gamma)

    Boundary conditions p=0 → 0 and p=1 → 1 are enforced exactly.
    For the TK form, computation is performed in log-domain for numerical
    stability near p=0 and p=1.

    Parameters
    ----------
    p : np.ndarray or float
        Probability/ies in [0, 1].
    form : {"tk", "prelec"}
        Functional form to use.
    gamma_gain : float
        Curvature parameter for the gain side. Must be in (0, 1].
    gamma_loss : float
        Curvature parameter for the loss side. Must be in (0, 1].
    delta : float
        Elevation parameter (Prelec only). Must be > 0.
    side : {"gain", "loss"}
        Which side's gamma to use.

    Returns
    -------
    np.ndarray or float
        Weighted probability/ies. Same type as input.

    Raises
    ------
    ValueError
        If parameter constraints are violated or p not in [0, 1].
    """
    gamma = gamma_gain if side == "gain" else gamma_loss

    if not (0 < gamma_gain <= 1):
        raise ValueError(f"gamma_gain must be in (0, 1], got {gamma_gain!r}")
    if not (0 < gamma_loss <= 1):
        raise ValueError(f"gamma_loss must be in (0, 1], got {gamma_loss!r}")
    if delta <= 0:
        raise ValueError(f"delta must be > 0, got {delta!r}")

    if form == "tk" and gamma < 0.28:
        warnings.warn(
            f"TK weighting with gamma={gamma} < 0.28 may be non-monotone.",
            UserWarning,
            stacklevel=2,
        )

    scalar_input = np.isscalar(p)
    arr = np.asarray(p, dtype=float)

    if np.any(arr < 0) or np.any(arr > 1):
        raise ValueError("p must be in [0, 1]")

    interior = (arr > 0) & (arr < 1)
    result = np.zeros_like(arr)
    result[arr >= 1] = 1.0

    if not np.any(interior):
        if scalar_input:
            return float(result)
        return result

    p_int = arr[interior]

    if form == "tk":
        log_p = np.log(p_int)
        log_1mp = np.log1p(-p_int)
        # log(w) = gamma*log_p - (1/gamma)*log(exp(gamma*log_p) + exp(gamma*log_1mp))
        a = gamma * log_p
        b = gamma * log_1mp
        # log-sum-exp: log(exp(a) + exp(b)) = max + log(1 + exp(min - max))
        m = np.maximum(a, b)
        log_denom = m + np.log1p(np.exp(np.minimum(a, b) - m))
        log_w = a - log_denom / gamma
        result[interior] = np.exp(log_w)
    elif form == "prelec":
        log_p = np.log(p_int)
        result[interior] = np.exp(-delta * (-log_p) ** gamma)
    else:
        raise ValueError(f"form must be 'tk' or 'prelec', got {form!r}")

    if scalar_input:
        return float(result)
    return result
