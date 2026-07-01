"""Multiple testing corrections for trial p-values."""

from __future__ import annotations

from typing import Any

import numpy as np


def bonferroni_holm_correction(
    p_values: list[float] | np.ndarray,
    *,
    method: str = "holm",
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Multiple testing correction for a set of p-values.

    Supports four methods:
        bonferroni  – family-wise error rate (FWER), most conservative
        holm        – step-down FWER control (Holm 1979), less conservative
        fdr_bh      – Benjamini-Hochberg FDR (1995)
        fdr_by      – Benjamini-Yekutieli FDR (2001), handles dependence

    Args:
        p_values: Array of raw p-values from individual hypothesis tests.
        method: One of "bonferroni", "holm", "fdr_bh", "fdr_by".
        alpha: Nominal significance level (default 0.05).

    Returns:
        corrected_p_values: np.ndarray (same order as input)
        is_significant_per_test: np.ndarray[bool] (uncorrected p <= alpha)
        is_significant_corrected: np.ndarray[bool] (after correction)
        method: str
        fdr_or_fwer: str ("FDR" for bh/by, "FWER" for bonferroni/holm)

    References:
        Bonferroni (1936); Holm (1979); Benjamini & Hochberg (1995);
        Benjamini & Yekutieli (2001).
    """
    p_arr = np.asarray(p_values, dtype=np.float64)
    m = len(p_arr)
    order = np.argsort(p_arr)
    p_sorted = p_arr[order]

    corrected = np.empty(m, dtype=np.float64)

    if method == "bonferroni":
        corrected_sorted = np.minimum(p_sorted * m, 1.0)
        fdr_or_fwer = "FWER"

    elif method == "holm":
        # step-down: corrected_p(k) = max over j<=k of p(j)*(m-j+1), capped at 1
        raw = p_sorted * np.arange(m, 0, -1)
        corrected_sorted = np.minimum(np.maximum.accumulate(raw), 1.0)
        fdr_or_fwer = "FWER"

    elif method == "fdr_bh":
        # BH: corrected_p(k) = p(k)*m/rank, processed in reverse for min-accumulation
        raw = p_sorted * m / np.arange(1, m + 1)
        # step-up: take running minimum from the largest rank backwards
        corrected_sorted = np.minimum(np.minimum.accumulate(raw[::-1])[::-1], 1.0)
        fdr_or_fwer = "FDR"

    elif method == "fdr_by":
        c_m = float(np.sum(1.0 / np.arange(1, m + 1)))
        raw = p_sorted * m * c_m / np.arange(1, m + 1)
        corrected_sorted = np.minimum(np.minimum.accumulate(raw[::-1])[::-1], 1.0)
        fdr_or_fwer = "FDR"

    else:
        raise ValueError(
            f"Unknown method: {method}. Choose 'bonferroni', 'holm', 'fdr_bh', or 'fdr_by'."
        )

    # Restore original order
    inv_order = np.empty(m, dtype=int)
    inv_order[order] = np.arange(m)
    corrected = corrected_sorted[inv_order]

    is_sig_uncorrected = p_arr <= alpha
    is_sig_corrected = corrected <= alpha

    return {
        "corrected_p_values": corrected,
        "is_significant_per_test": is_sig_uncorrected,
        "is_significant_corrected": is_sig_corrected,
        "method": method,
        "fdr_or_fwer": fdr_or_fwer,
    }
