"""Private helpers shared by oprim/technical submodules (H2 exempt from H1)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _to_array(x: np.ndarray | pd.Series) -> tuple[np.ndarray, bool, pd.Index | None]:
    """Convert input to float64 ndarray; track if original was Series."""
    if isinstance(x, pd.Series):
        return np.asarray(x, dtype=float), True, x.index
    return np.asarray(x, dtype=float), False, None


def _wrap(arr: np.ndarray, is_series: bool, index: pd.Index | None) -> np.ndarray | pd.Series:
    """Wrap result ndarray back to Series if input was Series."""
    if is_series:
        return pd.Series(arr, index=index)
    return arr


def _ema_recursive(arr: np.ndarray, window: int) -> np.ndarray:
    """EMA with recursive formula, adjust=False. Matches pd.ewm(span=w, adjust=False)."""
    alpha = 2.0 / (window + 1)
    out = np.empty(len(arr))
    out[0] = arr[0]
    for i in range(1, len(arr)):
        if np.isnan(arr[i]):
            out[i] = np.nan
        elif np.isnan(out[i - 1]):
            out[i] = arr[i]
        else:
            out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def _wilder_atr(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int,
) -> np.ndarray:
    """Full ATR series using Wilder smoothing. Returns array of length len(close)."""
    n = len(close)
    out = np.full(n, np.nan)
    if n < 2:
        return out
    trs = np.empty(n - 1)
    for i in range(1, n):
        trs[i - 1] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
    if n - 1 >= period:
        seed_idx = period - 1
        out[seed_idx + 1] = float(trs[:period].mean())
        for i in range(seed_idx + 2, n):
            out[i] = (out[i - 1] * (period - 1) + trs[i - 1]) / period
    return out
