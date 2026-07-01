"""A5 — Sector strength proxy (0-100 normalized score)."""

from __future__ import annotations

import warnings

import numpy as np


def sector_strength_proxy(
    *,
    returns: list[float] | np.ndarray,
    volumes: list[float] | np.ndarray | None = None,
    scoring: str = "return",
    lookback: int = 20,
) -> float:
    """Compute sector strength as a 0-100 normalized score.

    Parameters
    ----------
    returns : array-like
        Constituent returns (latest lookback period average or single-day).
    volumes : array-like, optional
        Constituent volumes (required for volume_adj_return mode).
    scoring : str
        One of "return", "volume_adj_return", "breadth".
    lookback : int
        Lookback period for context (used in warnings).

    Returns
    -------
    float in [0, 100].
    """
    arr = np.asarray(returns, dtype=float)
    valid = arr[~np.isnan(arr)]

    if len(valid) == 0:
        return 0.0

    if lookback < 5:
        warnings.warn(f"lookback={lookback} is short, results may be noisy", stacklevel=2)

    if scoring == "return":
        raw = float(np.mean(valid))
    elif scoring == "volume_adj_return":
        vol_arr = np.asarray(volumes if volumes is not None else np.ones_like(valid), dtype=float)
        vol_valid = vol_arr[~np.isnan(arr)][:len(valid)]
        total_vol = np.sum(vol_valid)
        if total_vol == 0:
            raw = float(np.mean(valid))
        else:
            raw = float(np.sum(valid * vol_valid[:len(valid)]) / total_vol)
    elif scoring == "breadth":
        raw = float(np.sum(valid > 0) / len(valid))
    else:
        raise ValueError(f"Unknown scoring mode: {scoring}")

    # Normalize to 0-100 using sigmoid-like mapping
    # raw is typically in [-0.1, 0.1] for returns, [0, 1] for breadth
    if scoring == "breadth":
        return float(np.clip(raw * 100, 0, 100))
    else:
        # Map [-0.05, 0.05] → [0, 100] linearly, clip
        normalized = (raw + 0.05) / 0.10 * 100
        return float(np.clip(normalized, 0, 100))
