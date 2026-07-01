"""oprim.zscore_signal — Rolling z-score signal for pairs-trading spread."""
from __future__ import annotations

from typing import Any


def zscore_signal(
    series: Any,
    *,
    lookback: int,
) -> dict[str, Any]:
    """Compute rolling z-scores for a spread series.

    Args:
        series: 1-D array-like of spread values, length T.
        lookback: Rolling window size (must be ≥ 2 and ≤ len(series)).

    Returns:
        Dict with keys:

        - ``zscore`` – Most recent z-score (scalar float).
        - ``zscores`` – Full array of z-scores (length T − lookback + 1).
        - ``mean`` – Rolling mean at the last window.
        - ``std`` – Rolling std (ddof=1) at the last window.
        - ``signal`` – ``"long"`` if zscore < −1, ``"short"`` if > +1, else ``"flat"``.

    Raises:
        ValueError: If *lookback* is invalid or series is too short.
    """
    import numpy as np  # noqa: PLC0415

    arr = np.asarray(series, dtype=float)
    T = len(arr)

    if lookback < 2:
        raise ValueError(f"lookback must be ≥ 2, got {lookback}")
    if T < lookback:
        raise ValueError(f"series too short (len={T}) for lookback={lookback}")

    zscores: list[float] = []
    for i in range(lookback - 1, T):
        window = arr[i - lookback + 1 : i + 1]
        mu = float(window.mean())
        sigma = float(window.std(ddof=1))
        z = (arr[i] - mu) / sigma if sigma > 0 else 0.0
        zscores.append(z)

    last_window = arr[T - lookback :]
    last_mean = float(last_window.mean())
    last_std = float(last_window.std(ddof=1))
    last_z = zscores[-1]

    if last_z < -1.0:
        signal = "long"
    elif last_z > 1.0:
        signal = "short"
    else:
        signal = "flat"

    return {
        "zscore": last_z,
        "zscores": zscores,
        "mean": last_mean,
        "std": last_std,
        "signal": signal,
    }
