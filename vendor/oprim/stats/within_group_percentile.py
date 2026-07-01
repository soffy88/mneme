"""A6 — Within-group percentile ranking."""

from __future__ import annotations

import warnings

import numpy as np


def within_group_percentile(
    *,
    values: list[float] | np.ndarray,
    target_idx: int,
    method: str = "rank",
) -> float:
    """Compute the percentile of target within its group.

    Parameters
    ----------
    values : array-like
        All values in the group (including target).
    target_idx : int
        Index of the target value in the array.
    method : str
        "rank" (default) or "interpolate".

    Returns
    -------
    float in [0, 1].
    """
    arr = np.asarray(values, dtype=float)
    n = len(arr)

    if target_idx < 0 or target_idx >= n:
        raise IndexError(f"target_idx={target_idx} out of range for group size {n}")

    if n == 1:
        warnings.warn("Group size is 1, returning 0.5", stacklevel=2)
        return 0.5

    target_val = arr[target_idx]

    if method == "rank":
        rank = float(np.sum(arr < target_val)) / (n - 1)
        return float(np.clip(rank, 0.0, 1.0))
    elif method == "interpolate":
        sorted_vals = np.sort(arr)
        # Linear interpolation of percentile
        rank_positions = np.linspace(0, 1, n)
        idx = np.searchsorted(sorted_vals, target_val, side="right") - 1
        idx = max(0, min(idx, n - 1))
        return float(rank_positions[idx])
    else:
        raise ValueError(f"Unknown method: {method}")
