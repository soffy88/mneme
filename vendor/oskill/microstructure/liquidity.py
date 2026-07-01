"""Market liquidity estimators: Kyle's lambda and Amihud illiquidity."""

from __future__ import annotations

import numpy as np


def kyle_lambda_estimator(
    returns: np.ndarray,
    signed_volume: np.ndarray,
    *,
    estimator: str = "regression",
    window: int = 20,
) -> float | np.ndarray:
    """Estimate Kyle's lambda (price impact coefficient).

    Kyle (1985): OLS of price change (return) on signed order flow.
    lambda = cov(returns, signed_volume) / var(signed_volume)

    Parameters
    ----------
    returns : np.ndarray
        Price returns (delta_p or log returns).
    signed_volume : np.ndarray
        Signed volume: positive for buys, negative for sells.
    estimator : str
        'regression': single OLS float over entire sample.
        'rolling': rolling OLS with the given window.
    window : int
        Window size for rolling estimator.

    Returns
    -------
    float or np.ndarray
        Single lambda for 'regression', rolling array for 'rolling'.
    """
    returns = np.asarray(returns, dtype=float)
    signed_volume = np.asarray(signed_volume, dtype=float)

    if len(returns) != len(signed_volume):
        raise ValueError("returns and signed_volume must have the same length")

    def _ols(r: np.ndarray, v: np.ndarray) -> float:
        var_v = np.var(v)
        if var_v == 0.0:
            return 0.0
        return float(np.cov(r, v, ddof=1)[0, 1] / var_v)

    if estimator == "regression":
        return _ols(returns, signed_volume)

    elif estimator == "rolling":
        n = len(returns)
        lam = np.full(n, np.nan)
        for i in range(window - 1, n):
            r_win = returns[i - window + 1 : i + 1]
            v_win = signed_volume[i - window + 1 : i + 1]
            lam[i] = _ols(r_win, v_win)
        return lam

    else:
        raise ValueError(f"Unknown estimator '{estimator}'. Use 'regression' or 'rolling'.")


def amihud_illiquidity(
    returns: np.ndarray,
    dollar_volumes: np.ndarray,
    *,
    window: int | None = None,
    annualize: bool = False,
) -> float | np.ndarray:
    """Amihud (2002) illiquidity ratio.

    ILLIQ_t = |return_t| / dollar_volume_t.
    Captures price impact per unit of dollar trading volume.

    Parameters
    ----------
    returns : np.ndarray
        Daily (or periodic) returns.
    dollar_volumes : np.ndarray
        Daily (or periodic) dollar trading volumes.
    window : int, optional
        If None, return single mean over all observations.
        If int, return rolling mean over that window.
    annualize : bool
        If True, multiply by 252 (trading days).

    Returns
    -------
    float or np.ndarray
        Illiquidity ratio(s). NaN where dollar_volume == 0.
    """
    returns = np.asarray(returns, dtype=float)
    dollar_volumes = np.asarray(dollar_volumes, dtype=float)

    if len(returns) != len(dollar_volumes):
        raise ValueError("returns and dollar_volumes must have the same length")

    # Element-wise ratio; NaN where dollar_volume == 0
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(dollar_volumes > 0, np.abs(returns) / dollar_volumes, np.nan)

    scale = 252.0 if annualize else 1.0

    if window is None:
        # Single mean ignoring NaN
        result = float(np.nanmean(ratio)) * scale
        return result
    else:
        n = len(ratio)
        rolling = np.full(n, np.nan)
        for i in range(n):
            win = ratio[max(0, i - window + 1) : i + 1]
            if len(win) > 0 and not np.all(np.isnan(win)):
                rolling[i] = np.nanmean(win) * scale
        return rolling
