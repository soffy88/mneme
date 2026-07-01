"""oprim.pbo_compute — Probability of Backtest Overfitting (Bailey et al.)."""
from __future__ import annotations

from typing import Any


def pbo_compute(
    is_sharpes: list[float],
    oos_sharpes: list[float],
) -> dict[str, Any]:
    """Estimate Probability of Backtest Overfitting via rank-based logistic.

    For each IS-optimal trial, computes what fraction of the time the OOS
    rank falls below the median — indicative of overfitting.

    Args:
        is_sharpes: In-sample Sharpe ratios for N strategy trials.
        oos_sharpes: Out-of-sample Sharpe ratios for the same N trials
            (same order as *is_sharpes*).

    Returns:
        Dict with keys:

        - ``pbo`` – PBO estimate in [0, 1].  > 0.5 signals overfitting.
        - ``best_is_idx`` – Index of the IS-optimal trial.
        - ``oos_normalized_rank`` – OOS rank of IS-optimal trial, normalised
          to [0, 1] (0 = worst OOS, 1 = best OOS).
        - ``lambda_`` – Log-odds of overfitting (logistic link).

    Raises:
        ValueError: If the two lists differ in length or are empty.
    """
    import math  # noqa: PLC0415

    n = len(is_sharpes)
    if n == 0:
        raise ValueError("is_sharpes must be non-empty")
    if len(oos_sharpes) != n:
        raise ValueError(
            f"is_sharpes and oos_sharpes must have equal length: {n} vs {len(oos_sharpes)}"
        )

    best_is_idx = max(range(n), key=lambda i: is_sharpes[i])

    # Rank of the IS-optimal strategy in the OOS distribution (0-based)
    oos_sorted_indices = sorted(range(n), key=lambda i: oos_sharpes[i])
    oos_rank_of_best = oos_sorted_indices.index(best_is_idx)
    oos_norm_rank = oos_rank_of_best / max(n - 1, 1)

    # PBO: probability that the IS-optimal strategy has below-median OOS performance
    # Via logistic transformation: lambda = log(w / (1 - w))  where w = 1 - norm_rank
    w = 1.0 - oos_norm_rank
    # Clip w away from 0/1 to avoid log(0)
    w_clip = max(1e-9, min(1.0 - 1e-9, w))
    lambda_ = math.log(w_clip / (1.0 - w_clip))

    # PBO = Pr(norm_rank < 0.5) = Pr(IS-optimal underperforms OOS median)
    pbo = 1.0 - oos_norm_rank

    return {
        "pbo": float(pbo),
        "best_is_idx": best_is_idx,
        "oos_normalized_rank": float(oos_norm_rank),
        "lambda_": float(lambda_),
    }
