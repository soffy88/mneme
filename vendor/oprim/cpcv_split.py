"""oprim.cpcv_split — Combinatorial Purged Cross-Validation splits."""
from __future__ import annotations

from typing import Any


def cpcv_split(
    data: Any,
    *,
    n_splits: int,
    embargo: int = 0,
) -> list[dict[str, Any]]:
    """Generate purged cross-validation folds with embargo gap.

    Divides *data* into *n_splits* contiguous folds.  Each fold acts as the
    test set once; training uses all other folds minus *embargo* observations
    adjacent to the test boundary (to prevent leakage).

    Args:
        data: Sequence of length T (list, numpy array, pandas Series, …).
        n_splits: Number of folds (k ≥ 2).
        embargo: Number of observations to drop from each side of the test
            boundary to prevent look-ahead leakage.

    Returns:
        List of *n_splits* dicts, each with:

        - ``train_idx`` – Sorted list of training indices.
        - ``test_idx``  – Sorted list of test indices.
        - ``fold`` – Fold number (0-based).

    Raises:
        ValueError: If *n_splits* < 2 or *data* is too short.
    """
    try:
        n = len(data)
    except TypeError:
        raise ValueError("data must be a sized sequence") from None

    if n_splits < 2:
        raise ValueError(f"n_splits must be ≥ 2, got {n_splits}")
    if n < n_splits:
        raise ValueError(f"data length ({n}) must be ≥ n_splits ({n_splits})")

    # Compute fold boundaries
    fold_size = n // n_splits
    boundaries: list[tuple[int, int]] = []
    for k in range(n_splits):
        start = k * fold_size
        end = (k + 1) * fold_size if k < n_splits - 1 else n
        boundaries.append((start, end))

    splits: list[dict[str, Any]] = []
    for fold_idx, (test_start, test_end) in enumerate(boundaries):
        test_idx = list(range(test_start, test_end))

        # Training indices = everything outside the test window + embargo gap
        embargo_start = max(0, test_start - embargo)
        embargo_end = min(n, test_end + embargo)

        train_idx = list(range(0, embargo_start)) + list(range(embargo_end, n))

        splits.append({
            "fold": fold_idx,
            "train_idx": train_idx,
            "test_idx": test_idx,
        })

    return splits
