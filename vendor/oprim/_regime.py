"""Regime-related atomic operations."""

from __future__ import annotations

import warnings
from itertools import groupby
from typing import Any, Literal

import numpy as np
import pandas as pd


def regime_filter_data(
    data: pd.DataFrame,
    regime_labels: pd.Series,
    target_regime: str | list[str],
    mode: Literal["hard", "soft"] = "hard",
    min_probability: float = 0.5,
) -> pd.DataFrame:
    """Filter data by regime labels.

    Parameters
    ----------
    data : pd.DataFrame
        Data to filter.
    regime_labels : pd.Series
        Regime labels aligned with data index.
    target_regime : str | list[str]
        Target regime(s) to keep.
    mode : {"hard", "soft"}
        Hard = string labels, soft = probability dicts.
    min_probability : float
        Minimum probability threshold (soft mode only).

    Returns
    -------
    pd.DataFrame
        Filtered data.
    """
    if isinstance(target_regime, str):
        target_regime = [target_regime]

    # Align indices
    common_idx = data.index.intersection(regime_labels.index)
    if common_idx.empty:
        raise ValueError("No overlapping indices between data and regime_labels")

    data_aligned = data.loc[common_idx]
    labels_aligned = regime_labels.loc[common_idx]

    if mode == "hard":
        # Check target exists
        unique_labels = labels_aligned.unique()
        for t in target_regime:
            if t not in unique_labels:
                raise ValueError(f"target_regime '{t}' not found in labels")
        mask = labels_aligned.isin(target_regime)
    else:  # soft
        # Check for non-dict elements in soft mode
        non_dict_mask = ~labels_aligned.apply(lambda x: isinstance(x, dict))
        if non_dict_mask.any():
            raise ValueError(
                f"mode='soft' requires dict values, found {non_dict_mask.sum()} non-dict elements"
            )

        # Vectorized: convert to DataFrame
        prob_df = pd.DataFrame(labels_aligned.tolist(), index=common_idx)
        mask = (prob_df[target_regime] >= min_probability).any(axis=1)

    return data_aligned[mask]


def regime_transition_matrix(
    regime_labels: pd.Series,
    states: list[str] | None = None,
    include_duration: bool = True,
) -> dict[str, Any]:
    """Estimate transition matrix and duration distribution from regime labels.

    Parameters
    ----------
    regime_labels : pd.Series
        Sequence of regime labels.
    states : list[str] | None
        Explicit state list. None = infer from data.
    include_duration : bool
        Whether to compute duration statistics.

    Returns
    -------
    dict with transition_matrix, duration_distribution, stationary_distribution, n_transitions.
    """
    labels = regime_labels.values
    if states is None:
        states = sorted(set(labels))

    n_states = len(states)
    state_idx = {s: i for i, s in enumerate(states)}

    # Count transitions and track unknown labels
    trans_counts = np.zeros((n_states, n_states))
    unknown_labels = set()
    skipped_transitions = 0

    for i in range(len(labels) - 1):
        if labels[i] in state_idx and labels[i + 1] in state_idx:
            trans_counts[state_idx[labels[i]], state_idx[labels[i + 1]]] += 1
        else:
            skipped_transitions += 1
            if labels[i] not in state_idx:
                unknown_labels.add(labels[i])
            if labels[i + 1] not in state_idx:
                unknown_labels.add(labels[i + 1])

    if skipped_transitions > 0 and states is not None:
        warnings.warn(
            f"{skipped_transitions} transitions skipped due to unknown labels: {unknown_labels}",
            stacklevel=2
        )

    # Normalize to probabilities
    row_sums = trans_counts.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1
    trans_matrix = trans_counts / row_sums

    trans_df = pd.DataFrame(trans_matrix, index=states, columns=states)

    # Stationary distribution - handle non-ergodic chains
    try:
        eigenvalues, eigenvectors = np.linalg.eig(trans_matrix.T)
        # Find eigenvalue closest to 1
        idx = np.argmin(np.abs(eigenvalues - 1.0))
        stationary = np.real(eigenvectors[:, idx])
        # Handle non-ergodic chains: force non-negative
        stationary = np.abs(stationary)
        if stationary.sum() == 0 or np.isnan(stationary.sum()):
            stationary = np.ones(n_states) / n_states
        else:
            stationary = stationary / stationary.sum()
    except Exception:  # pragma: no cover
        stationary = np.ones(n_states) / n_states  # pragma: no cover

    stat_dist = pd.Series(stationary, index=states)

    # Duration distribution - vectorized with groupby
    duration_dist = {}
    if include_duration:
        for state in states:
            durations = [sum(1 for _ in g) for k, g in groupby(labels) if k == state]
            if durations:
                duration_dist[state] = {
                    "mean": float(np.mean(durations)),
                    "median": float(np.median(durations)),
                    "min": int(np.min(durations)),
                    "max": int(np.max(durations)),
                    "count": len(durations),
                }
            else:
                duration_dist[state] = {"mean": 0, "median": 0, "min": 0, "max": 0, "count": 0}

    n_transitions = int(trans_counts.sum())

    return {
        "transition_matrix": trans_df,
        "duration_distribution": duration_dist,
        "stationary_distribution": stat_dist,
        "n_transitions": n_transitions,
    }


def regime_label_align(
    target_index: pd.DatetimeIndex,
    regime_labels: pd.Series,
    method: Literal["asof", "ffill"] = "asof",
    tolerance: pd.Timedelta | None = None,
) -> pd.Series:
    """Align regime labels to a target time index.

    Parameters
    ----------
    target_index : pd.DatetimeIndex
        Target timestamps to align to.
    regime_labels : pd.Series
        Regime labels with DatetimeIndex.
    method : {"asof", "ffill"}
        Alignment method.
    tolerance : pd.Timedelta | None
        Maximum time gap for alignment.

    Returns
    -------
    pd.Series
        Regime labels aligned to target_index.
    """
    if not isinstance(target_index, pd.DatetimeIndex):
        target_index = pd.DatetimeIndex(target_index)

    # Use merge_asof for both methods (ffill just differs in tolerance handling)
    target_df = pd.DataFrame(index=target_index)
    label_df = pd.DataFrame({"regime": regime_labels.values}, index=regime_labels.index)

    if method == "ffill" and tolerance is None:
        # ffill without tolerance: allow unlimited forward-fill
        merged = pd.merge_asof(
            target_df, label_df,
            left_index=True, right_index=True,
            direction="backward",
        )
    else:
        merged = pd.merge_asof(
            target_df, label_df,
            left_index=True, right_index=True,
            direction="backward",
            tolerance=tolerance,
        )

    return merged["regime"]
