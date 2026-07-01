"""Rolling correlation heatmap and option skew curve data oprims."""
from __future__ import annotations

from typing import Literal

import numpy as np


class OprimError(Exception):
    """Raised when oprim receives invalid input."""


def compute_rolling_correlation_heatmap(
    *,
    data_matrix: np.ndarray,
    window_size: int = 30,
    step_size: int = 1,
    method: Literal["pearson", "spearman"] = "pearson",
    column_labels: list[str] | None = None,
) -> dict:
    """Compute rolling correlation heatmap across multiple signals/assets.

    Args:
        data_matrix: Array of shape (T, N) — T timepoints × N signals.
        window_size: Rolling window length.
        step_size: Step between windows.
        method: Correlation method.
        column_labels: Optional column names.

    Returns:
        Dict with correlation_cube, window_labels, column_labels.

    Raises:
        OprimError: If inputs are invalid.

    Example:
        >>> data = np.random.randn(100, 4)
        >>> r = compute_rolling_correlation_heatmap(data_matrix=data, window_size=30)
        >>> len(r["correlation_cube"])
        71
    """
    T, N = data_matrix.shape
    if window_size > T:
        raise OprimError(f"window_size ({window_size}) > rows ({T})")
    if N < 2:
        raise OprimError("Need at least 2 columns to compute correlation")

    labels = column_labels or [f"col_{i}" for i in range(N)]
    cube = []
    win_labels = []

    for start in range(0, T - window_size + 1, step_size):
        window = data_matrix[start : start + window_size]
        if method == "spearman":
            ranked = np.apply_along_axis(lambda x: np.argsort(np.argsort(x)).astype(float), 0, window)
            corr = np.corrcoef(ranked.T)
        else:
            corr = np.corrcoef(window.T)
        cube.append([[round(float(corr[i, j]), 6) for j in range(N)] for i in range(N)])
        win_labels.append(str(start + window_size - 1))

    return {"correlation_cube": cube, "window_labels": win_labels, "column_labels": labels}


def compute_option_skew_curve_data(
    *,
    option_chain: dict,
    spot_price: float,
    maturity_filter: Literal["nearest", "all"] = "nearest",
) -> dict:
    """Transform raw option chain into skew curve data points.

    Args:
        option_chain: Raw option chain data (from fetch_option_vol_surface).
        spot_price: Current spot price for moneyness calculation.
        maturity_filter: "nearest" for closest expiry only, "all" for all.

    Returns:
        Dict with spot_price and slices (list of maturity slices with skew points).

    Raises:
        OprimError: If option chain is empty.

    Example:
        >>> compute_option_skew_curve_data(option_chain={"result": [...]}, spot_price=100000)
        {'spot_price': 100000, 'slices': [...]}
    """
    instruments = option_chain.get("result", option_chain.get("instruments", []))
    if not instruments:
        raise OprimError("Empty option chain data")

    by_maturity: dict[str, list[dict]] = {}
    for inst in instruments:
        mat = inst.get("expiration", inst.get("maturity", "unknown"))
        strike = inst.get("strike", 0)
        iv = inst.get("mark_iv", inst.get("iv", 0))
        if strike <= 0 or iv <= 0:
            continue
        by_maturity.setdefault(mat, []).append({
            "strike": float(strike),
            "moneyness": round(float(strike) / spot_price, 4),
            "iv": float(iv),
            "delta": inst.get("delta"),
            "volume": inst.get("volume"),
            "open_interest": inst.get("open_interest"),
        })

    slices = []
    for mat, points in sorted(by_maturity.items()):
        if len(points) < 5:
            continue
        points.sort(key=lambda p: p["strike"])
        atm_iv = min(points, key=lambda p: abs(p["moneyness"] - 1.0))["iv"]
        dte = inst.get("days_to_expiry", 0) if inst else 0
        slices.append({"maturity_label": mat, "days_to_expiry": dte, "skew_points": points, "atm_iv": atm_iv})

    if maturity_filter == "nearest" and slices:
        slices = [slices[0]]

    return {"spot_price": spot_price, "slices": slices}
