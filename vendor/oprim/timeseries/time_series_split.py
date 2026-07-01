"""A7 — Time-series train/val/oos split with gap."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import numpy as np


def time_series_split(
    *,
    dates: Sequence[date],
    train_pct: float = 0.6,
    val_pct: float = 0.2,
    gap_days: int = 0,
) -> dict[str, object]:
    """Split a date sequence into train / val / oos segments with optional gap.

    Parameters
    ----------
    dates : sequence of date
        Sorted date sequence (ascending).
    train_pct : float
        Fraction for training set (default 0.6).
    val_pct : float
        Fraction for validation set (default 0.2).
    gap_days : int
        Number of days to exclude between train and val (default 0).

    Returns
    -------
    dict with keys: train, val, oos (date tuples), split_dates, n_train, n_val, n_oos, gap_days.

    Raises
    ------
    ValueError
        If dates has fewer than 3 elements, or train_pct + val_pct > 1.0.
    """
    if train_pct + val_pct > 1.0:
        raise ValueError(f"train_pct + val_pct must be <= 1.0, got {train_pct + val_pct}")

    sorted_dates = sorted(dates)
    n = len(sorted_dates)

    if n < 3:
        raise ValueError(f"Need at least 3 dates, got {n}")

    n_train = int(np.floor(n * train_pct))
    n_val = int(np.floor(n * val_pct))

    if n_train < 1 or n_val < 1:
        raise ValueError("train_pct and val_pct must each yield at least 1 sample")

    # Train: [0, n_train)
    train_end_idx = n_train - 1
    train_end = sorted_dates[train_end_idx]

    # Find val_start: first date after train_end + gap_days
    gap_cutoff = sorted_dates[train_end_idx]
    val_start_idx = train_end_idx + 1
    if gap_days > 0:
        from datetime import timedelta

        gap_boundary = gap_cutoff + timedelta(days=gap_days)
        while val_start_idx < n and sorted_dates[val_start_idx] <= gap_boundary:
            val_start_idx += 1

    if val_start_idx >= n:
        raise ValueError("gap_days too large: no dates left for val/oos")

    # Distribute remaining dates between val and oos
    remaining = n - val_start_idx
    # Use original ratio to split remaining
    val_ratio = val_pct / (val_pct + (1.0 - train_pct - val_pct))
    n_val_actual = max(1, int(np.floor(remaining * val_ratio)))
    n_oos_actual = remaining - n_val_actual

    if n_oos_actual < 1:
        raise ValueError("Not enough dates for oos segment after gap")

    val_end_idx = val_start_idx + n_val_actual - 1
    oos_start_idx = val_end_idx + 1

    val_start = sorted_dates[val_start_idx]
    val_end = sorted_dates[val_end_idx]
    oos_start = sorted_dates[oos_start_idx]
    oos_end = sorted_dates[-1]

    return {
        "train": (sorted_dates[0], train_end),
        "val": (val_start, val_end),
        "oos": (oos_start, oos_end),
        "split_dates": {
            "train_end": train_end,
            "val_start": val_start,
            "val_end": val_end,
            "oos_start": oos_start,
        },
        "n_train": n_train,
        "n_val": n_val_actual,
        "n_oos": n_oos_actual,
        "gap_days": gap_days,
    }
