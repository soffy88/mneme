"""CUSUM filter for event-driven sampling (López de Prado 2018 Ch.2)."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd


def cusum_filter(
    series: np.ndarray | pd.Series,
    *,
    threshold: float = 0.05,
    method: Literal["symmetric", "asymmetric"] = "symmetric",
) -> dict[str, Any]:
    """CUSUM filter for event-driven sampling (López de Prado 2018 Ch.2).

    The CUSUM filter identifies significant cumulative deviations in a series,
    suitable for event-driven bar sampling. Events are generated when the
    cumulative sum exceeds the threshold from either direction.

    Symmetric:
        S_t^+ = max(0, S_{t-1}^+ + (x_t - x_{t-1}) - threshold/2)
        S_t^- = min(0, S_{t-1}^- + (x_t - x_{t-1}) + threshold/2)
        Event when S_t^+ > threshold or S_t^- < -threshold
        Reset S^+ and S^- to 0 after event.

    Asymmetric:
        S_t^+ = max(0, S_{t-1}^+ + (x_t - x_{t-1}))
        Event only when S_t^+ > threshold (no downside events)
        Reset after each event.

    Args:
        series: Price or value series (length T).
        threshold: Event threshold (default 0.05).
        method: 'symmetric' (default) detects moves in both directions,
                'asymmetric' detects only upward moves.

    Returns dict:
        - 'event_indices': list of int (positions in original series)
        - 'event_timestamps': pd.DatetimeIndex (if pandas input with DatetimeIndex,
                              else pd.Index matching input index)
        - 'n_events': int
    """
    is_series = isinstance(series, pd.Series)
    if is_series:
        x = series.values.astype(np.float64)
        index = series.index
    else:
        x = np.asarray(series, dtype=np.float64)
        index = None

    T = len(x)
    event_indices: list[int] = []

    s_plus = 0.0
    s_minus = 0.0

    for t in range(1, T):
        delta = x[t] - x[t - 1]

        if method == "symmetric":
            s_plus = max(0.0, s_plus + delta - threshold / 2.0)
            s_minus = min(0.0, s_minus + delta + threshold / 2.0)

            if s_plus > threshold or s_minus < -threshold:
                event_indices.append(t)
                s_plus = 0.0
                s_minus = 0.0
        else:
            # Asymmetric: only track upward moves
            s_plus = max(0.0, s_plus + delta)
            if s_plus > threshold:
                event_indices.append(t)
                s_plus = 0.0

    n_events = len(event_indices)

    if is_series and index is not None:
        event_timestamps = index[event_indices]
    else:
        event_timestamps = pd.Index(event_indices)

    return {
        "event_indices": event_indices,
        "event_timestamps": event_timestamps,
        "n_events": n_events,
    }
