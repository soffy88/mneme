"""Salience-based weighting primitives (Bordalo-Gennaioli-Shleifer)."""

from __future__ import annotations

import numpy as np


def salience_function(
    payoff: np.ndarray,
    reference: np.ndarray | float,
    *,
    theta: float = 0.1,
) -> np.ndarray:
    """Salience function (BGS 2012).

    Mathematical definition:

        sigma(x, x_bar) = |x - x_bar| / (|x| + |x_bar| + theta)

    Properties: sigma(x, x) = 0; symmetric; output in [0, 1).

    Parameters
    ----------
    payoff : np.ndarray
        Payoff values.
    reference : np.ndarray or float
        Reference / average payoff. Broadcast-compatible with payoff.
    theta : float
        Smoothing constant > 0 that prevents division by zero. Default 0.1.

    Returns
    -------
    np.ndarray
        Salience scores in [0, 1).

    Raises
    ------
    ValueError
        If theta <= 0.
    """
    if theta <= 0:
        raise ValueError(f"theta must be > 0, got {theta!r}")

    payoff_arr = np.asarray(payoff, dtype=float)
    ref_arr = np.asarray(reference, dtype=float)

    numerator = np.abs(payoff_arr - ref_arr)
    denominator = np.abs(payoff_arr) + np.abs(ref_arr) + theta
    return numerator / denominator


def salience_ranking_weights(
    salience_scores: np.ndarray,
    *,
    delta: float = 0.7,
    rank_dim: int = -1,
) -> np.ndarray:
    """Rank-order weights derived from salience scores (BGS 2012).

    States are ranked by descending salience along ``rank_dim``
    (rank index 0 = highest salience). Unnormalised weight for rank k is
    ``delta^k``. Weights are then normalised to sum to 1 along ``rank_dim``.

    When delta=1 all weights are uniform (1/n).

    Parameters
    ----------
    salience_scores : np.ndarray
        Non-negative salience scores. Shape arbitrary.
    delta : float
        Discounting parameter in (0, 1]. delta=1 gives uniform weights.
    rank_dim : int
        Axis along which states are ranked and weights assigned.

    Returns
    -------
    np.ndarray
        Normalised weights, same shape as salience_scores, summing to 1
        along rank_dim.

    Raises
    ------
    ValueError
        If delta not in (0, 1] or if any salience score is negative.
    """
    if not (0 < delta <= 1):
        raise ValueError(f"delta must be in (0, 1], got {delta!r}")

    scores = np.asarray(salience_scores, dtype=float)

    if np.any(scores < 0):
        raise ValueError("salience_scores must all be >= 0")

    # argsort descending: higher salience → lower rank index
    order = np.argsort(-scores, axis=rank_dim)
    # rank_indices[i] is the 0-based rank of element i along rank_dim
    rank_indices = np.argsort(order, axis=rank_dim)

    # Unnormalized weights: delta^rank
    unnorm = delta**rank_indices.astype(float)

    # Normalize along rank_dim
    total = unnorm.sum(axis=rank_dim, keepdims=True)
    weights: np.ndarray = unnorm / total
    return weights
