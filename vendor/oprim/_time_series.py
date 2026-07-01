"""Time series atomic operations."""

from __future__ import annotations

import warnings
from typing import Literal

import numpy as np
import pandas as pd
from scipy.stats import rankdata


def log_returns(
    prices: pd.Series,
    periods: list[int] | None = None,
    handle_gaps: Literal["skip", "interpolate", "raise"] = "skip",
) -> pd.DataFrame:
    """Compute log returns from a price series for multiple periods.

    r_t = ln(P_t / P_{t-period}) = ln(P_t) - ln(P_{t-period})

    Parameters
    ----------
    prices : pd.Series
        Price series (must be positive).
    periods : list[int], optional
        Periods for return calculation. Default [1, 5, 20, 60].
    handle_gaps : {"skip", "interpolate", "raise"}
        How to handle NaN gaps in prices.

    Returns
    -------
    pd.DataFrame
        Columns named ``log_ret_{p}d`` for each period.
    """
    if periods is None:
        periods = [1, 5, 20, 60]
    if not periods:
        raise ValueError("periods must not be empty")
    if any(p < 1 for p in periods):
        raise ValueError("All periods must be >= 1")

    if not isinstance(prices, pd.Series):
        prices = pd.Series(prices)

    # Handle gaps
    if handle_gaps == "raise" and prices.isna().any():
        raise ValueError("prices contains NaN values")
    elif handle_gaps == "interpolate":
        prices = prices.interpolate(method="linear")

    # Validate positive (non-NaN values)
    valid = prices.dropna()
    if (valid <= 0).any():
        raise ValueError("Prices must be positive")

    if len(prices) < max(periods):
        warnings.warn("prices length < max(periods), output will be all NaN", stacklevel=2)

    log_prices = np.log(prices)
    result = pd.DataFrame(index=prices.index)
    for p in periods:
        result[f"log_ret_{p}d"] = log_prices - log_prices.shift(p)
    return result


def cumulative_returns(
    returns: pd.Series,
    return_type: Literal["log", "simple"] = "log",
    initial_capital: float = 1.0,
    compound: bool = True,
) -> pd.Series:
    """Compute cumulative returns / equity curve from a returns series.

    Parameters
    ----------
    returns : pd.Series
        Return series.
    return_type : {"log", "simple"}
        Type of returns.
    initial_capital : float
        Starting capital (must be > 0).
    compound : bool
        Whether to compound (only relevant for simple returns).

    Returns
    -------
    pd.Series
        Equity curve.
    """
    if initial_capital <= 0:
        raise ValueError("initial_capital must be > 0")

    if not isinstance(returns, pd.Series):
        returns = pd.Series(returns)

    if return_type == "log":
        equity = initial_capital * np.exp(returns.cumsum())
    elif compound:
        # Warn if simple return < -1
        if (returns.dropna() < -1).any():
            warnings.warn("Simple returns < -1 detected (>100% loss)", stacklevel=2)
        equity = initial_capital * (1 + returns).cumprod()
    else:
        equity = initial_capital * (1 + returns.cumsum())

    return equity


def rolling_window_split(
    n_samples: int,
    window_size: int,
    step: int = 1,
    include_partial: bool = False,
) -> list[tuple[int, int]]:
    """Generate rolling window index pairs.

    Parameters
    ----------
    n_samples : int
        Total number of samples.
    window_size : int
        Size of each window.
    step : int
        Step between windows.
    include_partial : bool
        Whether to include partial windows at the end.

    Returns
    -------
    list[tuple[int, int]]
        List of (start, end) tuples (end inclusive).
    """
    if n_samples < 0:
        raise ValueError("n_samples must be >= 0")
    if window_size < 1:
        raise ValueError("window_size must be >= 1")
    if step < 1:
        raise ValueError("step must be >= 1")

    if n_samples < window_size:
        if include_partial and n_samples > 0:
            return [(0, n_samples - 1)]
        return []

    windows = []
    start = 0
    while start + window_size <= n_samples:
        windows.append((start, start + window_size - 1))
        start += step

    return windows


def lag_forward_fill(
    data: pd.Series | pd.DataFrame,
    max_gap: int | pd.Timedelta = 5,
    lag: int = 0,
    strict: bool = False,
) -> pd.Series | pd.DataFrame:
    """Forward-fill with max gap limit, then apply lag.

    Parameters
    ----------
    data : pd.Series | pd.DataFrame
        Input data.
    max_gap : int | pd.Timedelta
        Maximum consecutive NaN gap to fill.
    lag : int
        Number of periods to shift after filling.
    strict : bool
        If True, raise when gap exceeds max_gap.

    Returns
    -------
    pd.Series | pd.DataFrame
        Filled and lagged data.
    """
    if not isinstance(data, (pd.Series, pd.DataFrame)):
        data = pd.Series(data)

    # Check for gaps exceeding max_gap in strict mode
    if strict:
        if isinstance(data, pd.DataFrame):
            for col in data.columns:
                _check_gap(data[col], max_gap)
        else:
            _check_gap(data, max_gap)

    # Determine fill limit
    if isinstance(max_gap, int):
        limit = max_gap
    elif isinstance(max_gap, pd.Timedelta):
        # For Timedelta, compute max consecutive NaN periods allowed
        if isinstance(data.index, pd.DatetimeIndex) and len(data.index) > 1:
            # Use median gap between consecutive timestamps
            median_diff = pd.Series(data.index).diff().median()
            if pd.notna(median_diff) and median_diff.total_seconds() > 0:
                limit = int(max_gap.total_seconds() / median_diff.total_seconds())
            else:
                limit = None
        else:
            limit = None
    else:
        limit = None

    result = data.ffill(limit=limit)

    if lag != 0:
        result = result.shift(lag)

    return result


def _check_gap(series: pd.Series, max_gap: int | pd.Timedelta) -> None:
    """Check if any NaN gap exceeds max_gap."""
    if not series.isna().any():
        return
    is_nan = series.isna()
    groups = is_nan.ne(is_nan.shift()).cumsum()
    nan_groups = groups[is_nan]
    if nan_groups.empty:
        return
    max_consecutive = nan_groups.value_counts().max()

    if isinstance(max_gap, int):
        limit = max_gap
    elif isinstance(max_gap, pd.Timedelta):
        if isinstance(series.index, pd.DatetimeIndex) and len(series.index) > 1:
            median_diff = pd.Series(series.index).diff().median()
            if pd.notna(median_diff) and median_diff.total_seconds() > 0:
                limit = int(max_gap.total_seconds() / median_diff.total_seconds())
            else:
                limit = max_consecutive + 1
        else:
            limit = max_consecutive + 1
    else:
        limit = max_consecutive + 1

    if max_consecutive > limit:
        raise ValueError(f"Gap of {max_consecutive} exceeds max_gap={max_gap}")


def percentile_rank(
    data: pd.Series | pd.DataFrame,
    window: int | None = None,
    method: Literal["rolling", "cross_sectional", "expanding"] = "rolling",
    ties: Literal["average", "min", "max"] = "average",
) -> pd.Series | pd.DataFrame:
    """Compute percentile rank of each data point.

    Parameters
    ----------
    data : pd.Series | pd.DataFrame
        Input data.
    window : int | None
        Rolling window size (required for rolling method).
    method : {"rolling", "cross_sectional", "expanding"}
        Ranking method.
    ties : {"average", "min", "max"}
        How to handle tied values.

    Returns
    -------
    pd.Series | pd.DataFrame
        Percentile ranks in [0, 1].
    """
    if method == "rolling":
        if window is None:
            raise ValueError("window required for rolling method")
        if isinstance(data, pd.DataFrame):
            return data.apply(lambda col: _rolling_rank(col, window, ties))
        return _rolling_rank(data, window, ties)
    elif method == "expanding":
        if isinstance(data, pd.DataFrame):
            return data.apply(lambda col: _expanding_rank(col, ties))
        return _expanding_rank(data, ties)
    elif method == "cross_sectional":
        if not isinstance(data, pd.DataFrame):
            raise ValueError("cross_sectional method requires DataFrame")
        result = data.copy()
        for idx in data.index:
            row = data.loc[idx].values
            valid = ~np.isnan(row)
            if valid.sum() == 0:
                result.loc[idx] = np.nan
            else:
                ranks = np.full(len(row), np.nan)
                ranks[valid] = rankdata(row[valid], method=ties) / valid.sum()
                result.loc[idx] = ranks
        return result
    else:
        raise ValueError(f"Unknown method: {method}")


def _rolling_rank(series: pd.Series, window: int, ties: str) -> pd.Series:
    """Compute rolling percentile rank. Current value is last in window."""
    result = pd.Series(np.nan, index=series.index)
    for i in range(window - 1, len(series)):
        window_vals = series.iloc[i - window + 1 : i + 1].values
        valid_mask = ~np.isnan(window_vals)
        n_valid = valid_mask.sum()
        if n_valid == 0:
            continue
        # Current value is the last in the window
        cur_val = window_vals[-1]
        if np.isnan(cur_val):
            continue
        # Rank within valid values
        valid_vals = window_vals[valid_mask]
        ranks = rankdata(valid_vals, method=ties)
        # Find rank of current value (last valid position maps to last rank)
        # If current is valid, it's the last in valid_vals
        result.iloc[i] = ranks[-1] / n_valid
    return result


def _expanding_rank(series: pd.Series, ties: str) -> pd.Series:
    """Compute expanding percentile rank. Current value is last in window."""
    result = pd.Series(np.nan, index=series.index)
    for i in range(len(series)):
        cur_val = series.iloc[i]
        if np.isnan(cur_val):
            continue
        window_vals = series.iloc[: i + 1].values
        valid_mask = ~np.isnan(window_vals)
        n_valid = valid_mask.sum()
        if n_valid == 0:
            continue
        valid_vals = window_vals[valid_mask]
        ranks = rankdata(valid_vals, method=ties)
        # Current value is last in valid_vals
        result.iloc[i] = ranks[-1] / n_valid
    return result


def ewma_smooth(
    data: pd.Series,
    half_life: float | None = None,
    span: int | None = None,
    alpha: float | None = None,
    adjust: bool = True,
    ignore_na: bool = False,
) -> pd.Series:
    """Exponentially Weighted Moving Average.

    y_t = α × x_t + (1 - α) × y_{t-1}

    Exactly one of half_life, span, alpha must be specified.
    """
    specified = sum(x is not None for x in [half_life, span, alpha])
    if specified != 1:
        raise ValueError("Exactly one of half_life, span, alpha must be specified")

    if half_life is not None:
        if half_life <= 0:
            raise ValueError("half_life must be > 0")
        return data.ewm(halflife=half_life, adjust=adjust, ignore_na=ignore_na).mean()
    elif span is not None:
        if span < 1:
            raise ValueError("span must be >= 1")
        return data.ewm(span=span, adjust=adjust, ignore_na=ignore_na).mean()
    else:
        if not (0 < alpha <= 1):
            raise ValueError("alpha must be in (0, 1]")
        return data.ewm(alpha=alpha, adjust=adjust, ignore_na=ignore_na).mean()


def realized_vol(
    returns: pd.Series,
    window: int = 20,
    estimator: Literal["close_to_close", "garman_klass", "parkinson", "yang_zhang"] = "close_to_close",
    annualization_factor: int = 252,
    ohlc: pd.DataFrame | None = None,
) -> pd.Series:
    """Compute realized volatility with multiple estimators.

    Parameters
    ----------
    returns : pd.Series
        Return series (used for close_to_close).
    window : int
        Rolling window size.
    estimator : {"close_to_close", "garman_klass", "parkinson", "yang_zhang"}
        Volatility estimator.
    annualization_factor : int
        Annualization factor (252 equity, 365 crypto, 8760 crypto hourly).
    ohlc : pd.DataFrame | None
        OHLC data (required for garman_klass, parkinson, and yang_zhang).

    Returns
    -------
    pd.Series
        Annualized rolling volatility.
    """
    if window < 2:
        raise ValueError("window must be >= 2")
    if annualization_factor <= 0:
        raise ValueError("annualization_factor must be > 0")

    if estimator == "close_to_close":
        vol = returns.rolling(window).std() * np.sqrt(annualization_factor)
    elif estimator in ("garman_klass", "parkinson", "yang_zhang"):
        if ohlc is None:
            raise ValueError(f"ohlc required for estimator='{estimator}'")
        for col in ["open", "high", "low", "close"]:
            if col not in ohlc.columns:
                raise ValueError(f"ohlc must contain '{col}' column")

        h = np.log(ohlc["high"])
        l = np.log(ohlc["low"])
        o = np.log(ohlc["open"])
        c = np.log(ohlc["close"])

        if estimator == "garman_klass":
            # σ² = 0.5*(ln(H/L))² - (2ln2-1)*(ln(C/O))²
            var = 0.5 * (h - l) ** 2 - (2 * np.log(2) - 1) * (c - o) ** 2
        elif estimator == "parkinson":
            # σ² = (1/(4*ln2))*(ln(H/L))²
            var = (1 / (4 * np.log(2))) * (h - l) ** 2
        else:  # yang_zhang
            # Yang & Zhang 2000: σ²_yz = σ²_o + k·σ²_c + (1-k)·σ²_rs
            # σ²_o = overnight variance, σ²_c = close-to-close, σ²_rs = Rogers-Satchell

            # Overnight: log(O_t / C_{t-1})
            log_oc = o - c.shift(1)
            ov_mean = log_oc.rolling(window).mean()
            ov_var = ((log_oc - ov_mean) ** 2).rolling(window).mean()

            # Rogers-Satchell intraday variance
            log_ho = h - o
            log_lo = l - o
            log_co = c - o
            rs_var = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)
            rs_var = rs_var.rolling(window).mean()

            # Close-to-close variance with mean subtraction
            log_cc = c - c.shift(1)
            cc_mean = log_cc.rolling(window).mean()
            cc_var = ((log_cc - cc_mean) ** 2).rolling(window).mean()

            # Optimal k per Yang-Zhang
            k = 0.34 / (1.34 + (window + 1) / (window - 1))

            var = ov_var + k * cc_var + (1 - k) * rs_var

        vol = np.sqrt(var.rolling(window).mean() * annualization_factor)
    else:
        raise ValueError(f"Unknown estimator: {estimator}")

    return vol


def zscore_normalize(
    data: pd.Series | pd.DataFrame,
    window: int | None = None,
    min_periods: int = 20,
    clip_extreme: float | None = 5.0,
) -> pd.Series | pd.DataFrame:
    """Z-score normalization with rolling or expanding window.

    z_t = (x_t - μ_t) / σ_t

    Parameters
    ----------
    data : pd.Series | pd.DataFrame
        Input data.
    window : int | None
        Rolling window size. None = expanding.
    min_periods : int
        Minimum periods for calculation.
    clip_extreme : float | None
        Clip z-scores to [-clip, +clip]. None = no clipping.

    Returns
    -------
    pd.Series | pd.DataFrame
        Z-score normalized data.
    """
    if window is not None and window < min_periods:
        warnings.warn(f"window ({window}) < min_periods ({min_periods})", stacklevel=2)
        min_periods = window

    if window is None:
        roll = data.expanding(min_periods=min_periods)
    else:
        roll = data.rolling(window, min_periods=min_periods)

    mean = roll.mean()
    std = roll.std()
    z = (data - mean) / std

    if clip_extreme is not None:
        z = z.clip(-clip_extreme, clip_extreme)

    return z


def gap_detect(
    times: pd.DatetimeIndex,
    expected_interval: pd.Timedelta | None = None,
    asset_class: Literal["equity", "crypto", "fx", "commodity"] = "equity",
    severity_thresholds: dict | None = None,
) -> pd.DataFrame:
    """Detect gaps in time series data with severity classification.

    Parameters
    ----------
    times : pd.DatetimeIndex
        Timestamps to check.
    expected_interval : pd.Timedelta | None
        Expected interval. None = auto-detect from median diff.
    asset_class : {"equity", "crypto", "fx", "commodity"}
        Asset class for default thresholds.
    severity_thresholds : dict | None
        Custom thresholds {"short": Timedelta, "medium": Timedelta}.

    Returns
    -------
    pd.DataFrame
        Columns: [start_time, end_time, gap_duration, severity].
    """
    if len(times) < 2:
        return pd.DataFrame(columns=["start_time", "end_time", "gap_duration", "severity"])

    if not isinstance(times, pd.DatetimeIndex):
        times = pd.DatetimeIndex(times)

    if times.nunique() == 1:
        raise ValueError("All timestamps are identical")

    if expected_interval is None:
        diffs = pd.Series(times).diff().dropna()
        expected_interval = diffs.mode().iloc[0] if len(diffs.mode()) > 0 else diffs.median()

    if severity_thresholds is None:
        severity_thresholds = _default_severity(asset_class)

    diffs = pd.Series(times[1:]) - pd.Series(times[:-1])
    threshold = expected_interval * 1.5

    gaps = []
    for i, d in enumerate(diffs):
        if d > threshold:
            severity = _classify_severity(d, severity_thresholds)
            gaps.append({
                "start_time": times[i],
                "end_time": times[i + 1],
                "gap_duration": d,
                "severity": severity,
            })

    return pd.DataFrame(gaps, columns=["start_time", "end_time", "gap_duration", "severity"])


def _default_severity(asset_class: str) -> dict:
    if asset_class == "crypto":
        return {"short": pd.Timedelta(hours=6), "medium": pd.Timedelta(hours=24)}
    else:  # equity, fx, commodity
        return {"short": pd.Timedelta(days=1), "medium": pd.Timedelta(days=3)}


def _classify_severity(gap: pd.Timedelta, thresholds: dict) -> str:
    if gap <= thresholds["short"]:
        return "short"
    elif gap <= thresholds["medium"]:
        return "medium"
    return "long"


def resample_align(
    data_dict: dict[str, pd.DataFrame],
    target_freq: str = "D",
    method: Literal["last", "mean", "ohlc"] = "last",
    timezone: str = "UTC",
    forward_fill_limit: int | None = 5,
) -> pd.DataFrame:
    """Align multiple DataFrames to a common time frequency.

    Parameters
    ----------
    data_dict : dict[str, pd.DataFrame]
        Named DataFrames with DatetimeIndex.
    target_freq : str
        Target frequency (e.g., "D", "h").
    method : {"last", "mean", "ohlc"}
        Resampling method.
    timezone : str
        Target timezone.
    forward_fill_limit : int | None
        Max forward-fill periods after resampling.

    Returns
    -------
    pd.DataFrame
        Unified DataFrame with columns "{key}_{column}".
    """
    if not data_dict:
        raise ValueError("data_dict must not be empty")

    frames = []
    for key, df in data_dict.items():
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError(f"DataFrame '{key}' must have DatetimeIndex")

        # Convert timezone
        if df.index.tz is None:
            df = df.tz_localize("UTC")
        df = df.tz_convert(timezone)

        # Resample
        resampler = df.resample(target_freq)
        if method == "last":
            resampled = resampler.last()
        elif method == "mean":
            resampled = resampler.mean()
        else:  # ohlc
            resampled = resampler.ohlc()
            resampled.columns = ["_".join(c) if isinstance(c, tuple) else c for c in resampled.columns]

        if forward_fill_limit is not None and forward_fill_limit > 0:
            resampled = resampled.ffill(limit=forward_fill_limit)

        resampled.columns = [f"{key}_{col}" for col in resampled.columns]
        frames.append(resampled)

    result = pd.concat(frames, axis=1)
    return result


def purge_embargo_split(
    times: pd.DatetimeIndex,
    n_splits: int,
    embargo_pct: float = 0.01,
    label_horizon: int | pd.Timedelta = 0,
) -> list[dict[str, np.ndarray]]:
    """Purge-embargo cross-validation split per López de Prado 2018 Ch 7.

    Parameters
    ----------
    times : pd.DatetimeIndex
        Sorted datetime index.
    n_splits : int
        Number of CV splits (>= 2).
    embargo_pct : float
        Embargo percentage [0, 0.1].
    label_horizon : int | pd.Timedelta
        Label look-ahead horizon for purging.

    Returns
    -------
    list[dict[str, np.ndarray]]
        Each dict has 'train', 'test', 'embargo' index arrays.
    """
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")
    if not (0 <= embargo_pct <= 0.1):
        raise ValueError("embargo_pct must be in [0, 0.1]")

    if not isinstance(times, pd.DatetimeIndex):
        times = pd.DatetimeIndex(times)

    if not times.is_monotonic_increasing:
        raise ValueError("times must be sorted (monotonic increasing)")

    n = len(times)
    embargo_size = int(n * embargo_pct)
    indices = np.arange(n)

    # Create test folds
    fold_sizes = np.full(n_splits, n // n_splits)
    fold_sizes[: n % n_splits] += 1

    splits = []
    current = 0
    for fold_idx, fold_size in enumerate(fold_sizes):
        test_start = current
        test_end = current + fold_size
        test_idx = indices[test_start:test_end]

        # Embargo: indices right after test
        embargo_end = min(test_end + embargo_size, n)
        embargo_idx = indices[test_end:embargo_end]

        # Purge: remove train samples whose labels overlap with test
        if isinstance(label_horizon, pd.Timedelta):
            purge_mask = np.zeros(n, dtype=bool)
            test_start_time = times[test_start]
            for i in range(test_start):
                if times[i] + label_horizon >= test_start_time:
                    purge_mask[i] = True
        else:
            purge_start = max(0, test_start - label_horizon)
            purge_mask = np.zeros(n, dtype=bool)
            purge_mask[purge_start:test_start] = True

        # Train: everything not in test, embargo, or purged, before test block
        excluded = set(test_idx) | set(embargo_idx) | set(indices[purge_mask])
        # Only include train samples that come before test_start (no look-ahead)
        train_idx = np.array([i for i in indices[:test_start] if i not in excluded])

        # Skip any fold with empty train (per López de Prado, need min train samples)
        if len(train_idx) == 0:
            warnings.warn(f"Fold {fold_idx} skipped: empty train set", stacklevel=2)
            current = test_end
            continue

        splits.append({
            "train": train_idx,
            "test": test_idx,
            "embargo": embargo_idx,
        })
        current = test_end

    return splits
