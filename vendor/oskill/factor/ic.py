"""Information Coefficient (IC) between factor scores and forward returns."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy import stats


def factor_ic(
    factor: np.ndarray | pd.Series,
    forward_returns: np.ndarray | pd.Series,
    *,
    method: Literal["pearson", "spearman"] = "spearman",
    rolling_window: int | None = None,
) -> dict[str, Any]:
    """Information Coefficient: correlation between factor scores and forward returns.

    Computes the IC between the factor and realized forward returns. A positive
    IC indicates the factor has predictive power. IC/IC_std (ICIR) measures
    the consistency of the signal.

    Args:
        factor: Factor scores array (length N or T x N for cross-sectional).
                If 1D, treated as a single cross-section.
        forward_returns: Realized returns array matching factor shape.
        method: Correlation method — 'pearson' or 'spearman' (default).
        rolling_window: If set, compute rolling IC over this window length.

    Returns dict:
        - 'ic': float (mean IC across cross-sections or single IC)
        - 'ic_std': float (std of IC series if multiple cross-sections, else 0)
        - 'ic_t_stat': float
        - 'ic_p_value': float
        - 'icir': float (IC / IC_std, information ratio of the IC)
        - 'rolling_ic': pd.Series (if rolling_window set, else None)
    """
    if isinstance(factor, pd.Series):
        factor_arr = factor.values.astype(np.float64)
    else:
        factor_arr = np.asarray(factor, dtype=np.float64)

    if isinstance(forward_returns, pd.Series):
        ret_arr = forward_returns.values.astype(np.float64)
        ret_index = forward_returns.index
    else:
        ret_arr = np.asarray(forward_returns, dtype=np.float64)
        ret_index = None

    if factor_arr.shape != ret_arr.shape:
        raise ValueError(
            f"factor shape {factor_arr.shape} != forward_returns shape {ret_arr.shape}"
        )

    corr_fn = stats.spearmanr if method == "spearman" else stats.pearsonr

    def _ic_pair(f: np.ndarray, r: np.ndarray) -> float:
        """Compute IC for a single pair of arrays, ignoring NaNs."""
        mask = ~(np.isnan(f) | np.isnan(r))
        if np.sum(mask) < 3:
            return np.nan
        result = corr_fn(f[mask], r[mask])
        # scipy >=1.9 returns a result object; older returns (corr, pval) tuple
        if hasattr(result, "statistic"):
            return float(result.statistic)
        return float(result[0])

    if factor_arr.ndim == 1:
        # Single cross-section
        ic_val = _ic_pair(factor_arr, ret_arr)
        ic_series = np.array([ic_val])
    elif factor_arr.ndim == 2:
        # T x N: compute IC per row (time period)
        T = factor_arr.shape[0]
        ic_series = np.array([_ic_pair(factor_arr[t], ret_arr[t]) for t in range(T)])
    else:
        raise ValueError("factor must be 1D or 2D")

    valid_ic = ic_series[~np.isnan(ic_series)]
    if len(valid_ic) == 0:
        ic_mean = 0.0
        ic_std = 0.0
        ic_t_stat = 0.0
        ic_p_value = 1.0
        icir = 0.0
    elif len(valid_ic) == 1:
        ic_mean = float(valid_ic[0])
        ic_std = 0.0
        ic_t_stat = 0.0
        ic_p_value = 1.0
        icir = 0.0
    else:
        ic_mean = float(np.mean(valid_ic))
        ic_std = float(np.std(valid_ic, ddof=1))
        n = len(valid_ic)
        ic_t_stat = float(ic_mean / (ic_std / np.sqrt(n))) if ic_std > 0 else 0.0
        ic_p_value = float(2.0 * (1.0 - stats.t.cdf(abs(ic_t_stat), df=n - 1)))
        icir = float(ic_mean / ic_std) if ic_std > 0 else 0.0

    # Rolling IC
    rolling_ic_out = None
    if rolling_window is not None:
        if factor_arr.ndim == 2:
            roll_vals: list[float] = []
            for t in range(len(ic_series)):
                start = max(0, t - rolling_window + 1)
                window_ic = ic_series[start : t + 1]
                valid_window = window_ic[~np.isnan(window_ic)]
                roll_vals.append(float(np.mean(valid_window)) if len(valid_window) > 0 else np.nan)
            index = ret_index if ret_index is not None else np.arange(len(roll_vals))
            rolling_ic_out = pd.Series(roll_vals, index=index)
        else:
            # 1D: rolling window over single IC is trivial (constant)
            rolling_ic_out = pd.Series([ic_mean] * 1)

    return {
        "ic": ic_mean,
        "ic_std": ic_std,
        "ic_t_stat": ic_t_stat,
        "ic_p_value": ic_p_value,
        "icir": icir,
        "rolling_ic": rolling_ic_out,
    }
