"""Triple barrier labeling for financial ML (López de Prado 2018)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def triple_barrier_label(
    prices: np.ndarray | pd.Series,
    *,
    upper_barrier: float = 0.02,
    lower_barrier: float = -0.02,
    time_barrier: int = 5,
    side: np.ndarray | pd.Series | None = None,
) -> dict[str, Any]:
    """Triple barrier labeling for financial ML (López de Prado 2018).

    For each observation, find first barrier hit:
    - +1 if upper barrier hit first (price > entry * (1 + upper_barrier))
    - -1 if lower barrier hit first (price < entry * (1 + lower_barrier))
    - 0 if time barrier reached first

    Args:
        prices: Price series (length T).
        upper_barrier: Fractional upper return barrier (default 0.02 = 2%).
        lower_barrier: Fractional lower return barrier (default -0.02 = -2%).
        time_barrier: Number of periods to look ahead (default 5).
        side: Optional directional signal array of {-1, +1}. When provided,
              meta_labels are computed: 1 if side matches label else 0.

    Returns dict:
        - 'labels': array of {-1, 0, 1}
        - 'label_dates': list of barrier hit indices (relative to each entry)
        - 'meta_labels': array of {0, 1} (correct=1 if side matches label)
        - 'n_positive': int
        - 'n_negative': int
        - 'n_neutral': int
    """
    if isinstance(prices, pd.Series):
        price_arr = prices.values.astype(np.float64)
    else:
        price_arr = np.asarray(prices, dtype=np.float64)

    T = len(price_arr)
    labels = np.zeros(T, dtype=np.int8)
    label_dates: list[int] = []

    for t in range(T):
        entry = price_arr[t]
        if np.isnan(entry) or entry == 0:
            label_dates.append(t)
            continue

        upper_level = entry * (1.0 + upper_barrier)
        lower_level = entry * (1.0 + lower_barrier)

        hit = 0
        hit_idx = t  # default: time barrier at same index means last look
        end = min(t + time_barrier + 1, T)

        # Scan forward from t+1 to t+time_barrier inclusive
        for i in range(t + 1, end):
            p = price_arr[i]
            if np.isnan(p):
                continue
            if p >= upper_level:
                hit = 1
                hit_idx = i
                break
            elif p <= lower_level:
                hit = -1
                hit_idx = i
                break
        else:
            # time barrier reached — hit_idx is end of window
            hit_idx = end - 1

        labels[t] = hit
        label_dates.append(hit_idx)

    # Meta-labels
    if side is not None:
        if isinstance(side, pd.Series):
            side_arr = side.values
        else:
            side_arr = np.asarray(side)
        meta_labels = np.where(
            (side_arr != 0) & (labels != 0) & (np.sign(side_arr) == np.sign(labels)),
            1,
            0,
        ).astype(np.int8)
    else:
        meta_labels = np.zeros(T, dtype=np.int8)

    n_positive = int(np.sum(labels == 1))
    n_negative = int(np.sum(labels == -1))
    n_neutral = int(np.sum(labels == 0))

    return {
        "labels": labels,
        "label_dates": label_dates,
        "meta_labels": meta_labels,
        "n_positive": n_positive,
        "n_negative": n_negative,
        "n_neutral": n_neutral,
    }
