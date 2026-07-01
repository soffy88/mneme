"""oprim.cointegration_test — Engle-Granger cointegration test."""
from __future__ import annotations

from typing import Any


def cointegration_test(
    series_a: Any,
    series_b: Any,
    *,
    trend: str = "c",
) -> dict[str, Any]:
    """Test two time series for cointegration (Engle-Granger two-step).

    Args:
        series_a: First price series, array-like of length T.
        series_b: Second price series, array-like of length T.
        trend: Deterministic term — ``"c"`` (constant), ``"ct"``
            (constant + trend), ``"n"`` (none).

    Returns:
        Dict with keys:

        - ``t_stat`` – ADF t-statistic on the residuals.
        - ``p_value`` – MacKinnon p-value.
        - ``crit_values`` – Dict ``{"1%": …, "5%": …, "10%": …}``.
        - ``cointegrated`` – True when ``p_value < 0.05``.
        - ``hedge_ratio`` – OLS coefficient (series_b regressed on series_a).

    Raises:
        ValueError: If the series have different lengths or fewer than 10 obs.
    """
    import numpy as np  # noqa: PLC0415
    from statsmodels.tsa.stattools import coint  # noqa: PLC0415

    a = np.asarray(series_a, dtype=float)
    b = np.asarray(series_b, dtype=float)

    if len(a) != len(b):
        raise ValueError(f"series must have equal length: {len(a)} vs {len(b)}")
    if len(a) < 10:
        raise ValueError(f"series too short for cointegration test: {len(a)} < 10")

    t_stat, p_value, crit_values = coint(a, b, trend=trend)

    # OLS hedge ratio
    from numpy.linalg import lstsq  # noqa: PLC0415

    X = np.column_stack([a, np.ones(len(a))])
    hedge_ratio = float(lstsq(X, b, rcond=None)[0][0])

    return {
        "t_stat": float(t_stat),
        "p_value": float(p_value),
        "crit_values": {
            "1%": float(crit_values[0]),
            "5%": float(crit_values[1]),
            "10%": float(crit_values[2]),
        },
        "cointegrated": bool(p_value < 0.05),
        "hedge_ratio": hedge_ratio,
    }
