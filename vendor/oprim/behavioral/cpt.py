"""Cumulative Prospect Theory (CPT) value function."""

from __future__ import annotations

import numpy as np


def cpt_value_function(
    x: np.ndarray | float,
    *,
    reference_point: float = 0.0,
    alpha: float = 0.88,
    beta: float = 0.88,
    loss_aversion: float = 2.25,
) -> np.ndarray | float:
    """Kahneman-Tversky CPT value function.

    Mathematical definition:

        v(x) = (x - r)^alpha                    if x >= r
               -lambda * (r - x)^beta           if x < r

    where r is the reference point and lambda is the loss aversion coefficient.
    Power operations use the sign-preserving form ``sign(d) * |d|^exponent`` to
    avoid complex numbers for fractional exponents.

    Parameters
    ----------
    x : np.ndarray or float
        Outcome(s) to evaluate.
    reference_point : float
        Reference point r. Default 0.0.
    alpha : float
        Gain curvature. Must be in (0, 1].
    beta : float
        Loss curvature. Must be in (0, 1].
    loss_aversion : float
        Loss aversion coefficient lambda. Must be >= 1.

    Returns
    -------
    np.ndarray or float
        Value(s). Returns the same type as input (scalar → scalar, array → array).

    Raises
    ------
    ValueError
        If parameter constraints are violated.
    """
    if not (0 < alpha <= 1):
        raise ValueError(f"alpha must be in (0, 1], got {alpha!r}")
    if not (0 < beta <= 1):
        raise ValueError(f"beta must be in (0, 1], got {beta!r}")
    if loss_aversion < 1:
        raise ValueError(f"loss_aversion must be >= 1, got {loss_aversion!r}")

    scalar_input = np.isscalar(x)
    arr = np.asarray(x, dtype=float)

    deviation = arr - reference_point
    gain_mask = deviation >= 0

    result = np.empty_like(arr)
    result[gain_mask] = np.abs(deviation[gain_mask]) ** alpha
    result[~gain_mask] = -loss_aversion * np.abs(deviation[~gain_mask]) ** beta

    if scalar_input:
        return float(result)
    return result
