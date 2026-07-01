"""Compute peer percentile ranking for a student's metric.

Pure algorithm, no LLM.  Compares a student's value against a peer distribution
and returns the percentile rank + distribution metadata.

Version: oprim v3.3.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from oprim.types import PeerPercentileResult


def compute_peer_percentile(
    student_value: float,
    peer_values: list[float] | np.ndarray,
    *,
    method: str = "rank",
) -> PeerPercentileResult:
    """Compute the percentile rank of a student value within a peer distribution.

    Parameters
    ----------
    student_value : float
        The student's metric value.
    peer_values : list[float] | np.ndarray
        Distribution of peer values (must be non-empty).
    method : str
        "rank" — standard percentile rank (fraction of peers ≤ student).
        "modified" — (rank - 0.5) / N for continuity correction.

    Returns
    -------
    PeerPercentileResult
        Percentile (0–100), distribution stats, and bucket label.

    Raises
    ------
    ValueError
        If peer_values is empty.

    Examples
    --------
    >>> compute_peer_percentile(85, [60, 70, 80, 90, 100])
    PeerPercentileResult(student_value=85, percentile=60.0, ...)
    """
    if len(peer_values) == 0:
        raise ValueError("peer_values must be non-empty")

    arr = np.asarray(peer_values, dtype=np.float64)
    n = len(arr)

    # Count how many peers are strictly below / equal / above
    n_below = int(np.sum(arr < student_value))
    n_equal = int(np.sum(arr == student_value))

    if method == "modified":
        # Modified percentile: (rank - 0.5) / N * 100
        rank = n_below + 0.5 * (n_equal + 1)
        percentile = (rank / n) * 100.0
    else:
        # Standard: fraction of peers ≤ student
        percentile = ((n_below + 0.5 * n_equal) / n) * 100.0

    percentile = max(0.0, min(100.0, percentile))

    peer_mean = float(np.mean(arr))
    peer_std = float(np.std(arr, ddof=1)) if n > 1 else 0.0

    bucket = _percentile_to_bucket(percentile)

    return PeerPercentileResult(
        student_value=student_value,
        percentile=round(percentile, 2),
        peer_count=n,
        peer_mean=round(peer_mean, 4),
        peer_std=round(peer_std, 4),
        distribution_bucket=bucket,
    )


def compute_percentile_batch(
    student_values: dict[str, float],
    peer_distributions: dict[str, list[float] | np.ndarray],
    *,
    method: str = "rank",
) -> dict[str, PeerPercentileResult]:
    """Compute percentiles for multiple metrics in one call.

    Parameters
    ----------
    student_values : dict[str, float]
        Mapping of metric_name -> student_value.
    peer_distributions : dict[str, list[float] | np.ndarray]
        Mapping of metric_name -> peer distribution.
    method : str
        Percentile method (passed to compute_peer_percentile).

    Returns
    -------
    dict[str, PeerPercentileResult]
        Mapping of metric_name -> result.
    """
    results: dict[str, PeerPercentileResult] = {}
    for key in student_values:
        if key in peer_distributions and len(peer_distributions[key]) > 0:
            results[key] = compute_peer_percentile(
                student_values[key], peer_distributions[key], method=method
            )
    return results


def _percentile_to_bucket(pct: float) -> str:
    """Map a percentile (0–100) to a human-readable bucket string."""
    if pct >= 90:
        return "top_10%"
    if pct >= 75:
        return "top_25%"
    if pct >= 50:
        return "upper_half"
    if pct >= 25:
        return "lower_half"
    if pct >= 10:
        return "bottom_25%"
    return "bottom_10%"
