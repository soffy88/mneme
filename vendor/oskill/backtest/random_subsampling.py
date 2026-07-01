"""Random Subsampling Validation (López de Prado 2018, Ch.7.4)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def random_subsampling_validation(
    X: np.ndarray | pd.DataFrame,
    y: np.ndarray | pd.Series,
    estimator: Any,
    *,
    n_iterations: int = 100,
    test_size: float = 0.2,
    purge_pct: float = 0.0,
    embargo_pct: float = 0.0,
    seed: int | None = None,
) -> dict[str, Any]:
    """Random Subsampling Validation with optional embargo/purge.

    At each iteration a random contiguous block of test_size fraction of
    observations is held out for testing. The training set excludes the test
    block plus embargo/purge buffers, preventing lookahead leakage.

    Algorithm (López de Prado 2018, Ch.7.4):
        For each iteration:
            1. Draw random contiguous test block of size int(T * test_size)
            2. Embargo zone = embargo_periods rows after test end
            3. Train = all rows not in test ∪ embargo zone
            4. Skip if train < 10 obs
            5. Fit and score estimator

    Classification detected when unique(y) <= 10 (accuracy).
    Regression otherwise (R²).

    Args:
        X: Feature matrix (T, P).
        y: Target vector (T,).
        estimator: Object with .fit(X, y) and .predict(X).
        n_iterations: Number of subsampling iterations.
        test_size: Fraction of T to use as test block.
        purge_pct: Fraction of T to purge before test start.
        embargo_pct: Fraction of T to embargo after test end.
        seed: Random seed.

    Returns:
        mean_score: float
        std_score: float
        score_distribution: np.ndarray
        score_5th_pct: float
        score_95th_pct: float
        n_iterations_completed: int

    Reference:
        López de Prado (2018), Ch.7.4.
    """
    if isinstance(X, pd.DataFrame):
        X_arr = X.values
    else:
        X_arr = np.asarray(X)

    if isinstance(y, pd.Series):
        y_arr = y.values
    else:
        y_arr = np.asarray(y)

    T = len(X_arr)
    rng = np.random.default_rng(seed)

    block_size = max(1, int(T * test_size))
    embargo_periods = max(1, int(T * embargo_pct)) if embargo_pct > 0 else 0
    purge_periods = max(1, int(T * purge_pct)) if purge_pct > 0 else 0

    is_classification = len(np.unique(y_arr)) <= 10

    def _score(y_true: np.ndarray, y_pred: np.ndarray) -> float:
        if is_classification:
            return float(np.mean(y_true == y_pred))
        ss_res = float(np.sum((y_true - y_pred) ** 2))
        ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
        if ss_tot < 1e-12:
            return 0.0
        return float(1.0 - ss_res / ss_tot)

    scores: list[float] = []

    for _ in range(n_iterations):
        max_start = T - block_size
        if max_start <= 0:
            test_start = 0
        else:
            test_start = int(rng.integers(0, max_start + 1))
        test_end = min(T, test_start + block_size)

        excl_start = max(0, test_start - purge_periods)
        excl_end = min(T, test_end + embargo_periods)

        train_mask = np.ones(T, dtype=bool)
        train_mask[excl_start:excl_end] = False
        train_idx = np.where(train_mask)[0]

        if len(train_idx) < 10:
            continue

        test_idx = np.arange(test_start, test_end)

        try:
            estimator.fit(X_arr[train_idx], y_arr[train_idx])
            y_pred = estimator.predict(X_arr[test_idx])
            scores.append(_score(y_arr[test_idx], y_pred))
        except Exception:
            continue

    if not scores:
        scores = [0.0]

    scores_arr = np.array(scores)

    return {
        "mean_score": float(np.mean(scores_arr)),
        "std_score": float(np.std(scores_arr, ddof=1)) if len(scores_arr) > 1 else 0.0,
        "score_distribution": scores_arr,
        "score_5th_pct": float(np.percentile(scores_arr, 5)),
        "score_95th_pct": float(np.percentile(scores_arr, 95)),
        "n_iterations_completed": len(scores_arr),
    }
