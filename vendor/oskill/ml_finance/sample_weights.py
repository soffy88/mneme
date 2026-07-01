"""Sample weights based on event uniqueness (López de Prado 2018 Ch.4)."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd


def sample_uniqueness_weights(
    barrier_events: pd.DataFrame,
    *,
    method: Literal["concurrent", "uniqueness"] = "uniqueness",
) -> np.ndarray:
    """Weights based on sample uniqueness (López de Prado 2018 Ch.4).

    Events that overlap with many others carry less information. This function
    assigns higher weights to more unique (less overlapping) events.

    barrier_events: DataFrame with columns ['event_start', 'event_end']
                    (integer indices into the time series).

    For each event i:
        1. Count how many events overlap at each time step t in [start_i, end_i]
        2. Uniqueness_i = mean(1/concurrency_t) over event window
        3. Weight = uniqueness_i / sum(all uniqueness)

    Args:
        barrier_events: DataFrame with 'event_start' and 'event_end' columns
                        (integer indices, inclusive).
        method: 'uniqueness' (default) or 'concurrent' (returns raw concurrency).

    Returns:
        Normalized weights array (length = len(barrier_events)).
    """
    events = barrier_events.copy()
    n = len(events)
    if n == 0:
        return np.array([], dtype=np.float64)

    starts = events["event_start"].values.astype(np.int64)
    ends = events["event_end"].values.astype(np.int64)

    # Find total time range
    t_min = int(np.min(starts))
    t_max = int(np.max(ends))
    T = t_max - t_min + 1

    # Build concurrency array: concurrency[t] = number of events active at t
    concurrency = np.zeros(T, dtype=np.float64)
    for i in range(n):
        s = int(starts[i]) - t_min
        e = int(ends[i]) - t_min + 1  # inclusive end
        concurrency[s:e] += 1.0

    if method == "concurrent":
        # Return inverse concurrency per event (average)
        weights = np.zeros(n, dtype=np.float64)
        for i in range(n):
            s = int(starts[i]) - t_min
            e = int(ends[i]) - t_min + 1
            c = concurrency[s:e]
            c_safe = np.where(c > 0, c, 1.0)
            weights[i] = float(np.mean(1.0 / c_safe))
    else:
        # Uniqueness: mean(1/concurrency) over event window
        uniqueness = np.zeros(n, dtype=np.float64)
        for i in range(n):
            s = int(starts[i]) - t_min
            e = int(ends[i]) - t_min + 1
            c = concurrency[s:e]
            c_safe = np.where(c > 0, c, 1.0)
            uniqueness[i] = float(np.mean(1.0 / c_safe))

        total = np.sum(uniqueness)
        if total > 0:
            weights = uniqueness / total
        else:
            weights = np.ones(n, dtype=np.float64) / n

    return weights


def return_attribution_weights(
    barrier_events: pd.DataFrame,
    returns: np.ndarray | pd.Series,
    *,
    average_uniqueness: bool = True,
) -> np.ndarray:
    """Weights based on absolute return magnitude in label window.

    Assigns higher weights to events with larger absolute returns,
    adjusted for concurrency (overlapping events share the return signal).

    barrier_events: DataFrame with columns ['event_start', 'event_end']
    returns: Array of returns indexed by integer position.

    Weight_i = sum(|return_t| / concurrency_t for t in [start_i, end_i])
    Normalized by sum of all weights.

    Args:
        barrier_events: DataFrame with 'event_start' and 'event_end' columns.
        returns: Return series (length >= max event_end + 1).
        average_uniqueness: If True, divide each term by concurrency (default True).

    Returns:
        Normalized weights array (length = len(barrier_events)).
    """
    if isinstance(returns, pd.Series):
        ret_arr = returns.values.astype(np.float64)
    else:
        ret_arr = np.asarray(returns, dtype=np.float64)

    events = barrier_events.copy()
    n = len(events)
    if n == 0:
        return np.array([], dtype=np.float64)

    starts = events["event_start"].values.astype(np.int64)
    ends = events["event_end"].values.astype(np.int64)

    t_min = int(np.min(starts))
    t_max = int(np.max(ends))
    T = t_max - t_min + 1

    # Build concurrency
    concurrency = np.zeros(T, dtype=np.float64)
    for i in range(n):
        s = int(starts[i]) - t_min
        e = int(ends[i]) - t_min + 1
        concurrency[s:e] += 1.0

    weights = np.zeros(n, dtype=np.float64)
    for i in range(n):
        s = int(starts[i])
        e = int(ends[i]) + 1
        # Clamp to returns array bounds
        s_c = max(0, s)
        e_c = min(len(ret_arr), e)
        if s_c >= e_c:
            continue
        ret_seg = np.abs(ret_arr[s_c:e_c])
        if average_uniqueness:
            s_rel = s_c - t_min
            e_rel = e_c - t_min
            c_seg = concurrency[s_rel:e_rel]
            c_safe = np.where(c_seg > 0, c_seg, 1.0)
            weights[i] = float(np.sum(ret_seg / c_safe))
        else:
            weights[i] = float(np.sum(ret_seg))

    total = np.sum(weights)
    if total > 0:
        weights = weights / total
    else:
        weights = np.ones(n, dtype=np.float64) / n

    return weights
