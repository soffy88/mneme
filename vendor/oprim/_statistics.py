"""Statistics atomic operations."""

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy import stats


def bootstrap_ci(
    data: np.ndarray,
    statistic_fn: Callable[[np.ndarray], float],
    n_bootstrap: int = 1000,
    confidence_level: float = 0.95,
    method: Literal["percentile", "bca", "basic"] = "percentile",
    random_state: int | None = None,
) -> dict[str, float]:
    """Non-parametric bootstrap confidence interval.

    Parameters
    ----------
    data : np.ndarray
        Input data array.
    statistic_fn : callable
        Function that computes a scalar statistic from an array.
    n_bootstrap : int
        Number of bootstrap resamples.
    confidence_level : float
        Confidence level in (0, 1).
    method : {"percentile", "bca", "basic"}
        CI method.
    random_state : int | None
        Random seed for reproducibility.

    Returns
    -------
    dict with point_estimate, ci_lower, ci_upper, se, n_bootstrap, method.
    """
    data = np.asarray(data, dtype=np.float64)
    data = data[~np.isnan(data)]
    if data.size == 0:
        raise ValueError("data must not be empty (after removing NaN)")
    if not (0 < confidence_level < 1):
        raise ValueError("confidence_level must be in (0, 1)")
    if n_bootstrap < 100:
        warnings.warn("n_bootstrap < 100 may give unreliable estimates", stacklevel=2)
    if data.size > 1000 and method == "bca":
        warnings.warn(f"BCa with n={data.size} may be slow (O(n²) jackknife)", stacklevel=2)

    rng = np.random.default_rng(random_state)
    point_estimate = statistic_fn(data)

    # Vectorized bootstrap
    indices = rng.integers(0, len(data), size=(n_bootstrap, len(data)))
    boot_samples = data[indices]
    boot_stats = np.array([statistic_fn(s) for s in boot_samples])

    # Remove NaN results
    valid = ~np.isnan(boot_stats)
    if valid.sum() < n_bootstrap * 0.5:
        raise ValueError("More than 50% of bootstrap samples returned NaN")
    boot_stats = boot_stats[valid]

    alpha = 1 - confidence_level
    se = float(np.std(boot_stats, ddof=1))

    if method == "percentile":
        ci_lower = float(np.percentile(boot_stats, 100 * alpha / 2))
        ci_upper = float(np.percentile(boot_stats, 100 * (1 - alpha / 2)))
    elif method == "basic":
        ci_lower = float(2 * point_estimate - np.percentile(boot_stats, 100 * (1 - alpha / 2)))
        ci_upper = float(2 * point_estimate - np.percentile(boot_stats, 100 * alpha / 2))
    elif method == "bca":
        # Bias correction
        z0 = stats.norm.ppf(np.mean(boot_stats < point_estimate))
        # Acceleration (jackknife) - corrected formula
        n = len(data)
        jack_stats = np.array([statistic_fn(np.delete(data, i)) for i in range(n)])
        jack_mean = jack_stats.mean()
        # BCa acceleration: a = sum((jack_mean - jack_i)^3) / (6 * sum((jack_mean - jack_i)^2)^1.5)
        diff = jack_mean - jack_stats
        num = np.sum(diff ** 3)
        den = 6 * (np.sum(diff ** 2) ** 1.5)
        a = num / den if den != 0 else 0.0

        z_alpha_low = stats.norm.ppf(alpha / 2)
        z_alpha_high = stats.norm.ppf(1 - alpha / 2)

        alpha1 = stats.norm.cdf(z0 + (z0 + z_alpha_low) / (1 - a * (z0 + z_alpha_low)))
        alpha2 = stats.norm.cdf(z0 + (z0 + z_alpha_high) / (1 - a * (z0 + z_alpha_high)))

        ci_lower = float(np.percentile(boot_stats, 100 * alpha1))
        ci_upper = float(np.percentile(boot_stats, 100 * alpha2))
    else:
        raise ValueError(f"Unknown method: {method}")

    return {
        "point_estimate": float(point_estimate),
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "se": se,
        "n_bootstrap": n_bootstrap,
        "method": method,
    }


def percentile_ci(
    samples: np.ndarray,
    quantiles: list[float] | None = None,
    interpolation: str = "linear",
) -> dict[str, float]:
    """Compute percentile-based confidence intervals from samples.

    Parameters
    ----------
    samples : np.ndarray
        Sample array.
    quantiles : list[float]
        Quantiles to compute (each in [0, 1]).
    interpolation : str
        Interpolation method for numpy.percentile.

    Returns
    -------
    dict mapping "q_{q}" to float values.
    """
    if quantiles is None:
        quantiles = [0.05, 0.5, 0.95]

    for q in quantiles:
        if not (0 <= q <= 1):
            raise ValueError(f"quantile {q} not in [0, 1]")

    samples = np.asarray(samples, dtype=np.float64)
    valid = samples[~np.isnan(samples)]

    if valid.size == 0:
        return {f"q_{q}": np.nan for q in quantiles}

    result = {}
    for q in quantiles:
        result[f"q_{q}"] = float(np.percentile(valid, q * 100, method=interpolation))
    return result


def distribution_summary(
    data: np.ndarray,
    percentiles: list[float] | None = None,
) -> dict[str, float]:
    """Unified distribution descriptive statistics.

    Parameters
    ----------
    data : np.ndarray
        Input data.
    percentiles : list[float]
        Percentiles to compute (each in [0, 1]).

    Returns
    -------
    dict with mean, median, std, skew, kurtosis_excess, n, n_nan, min, max, and quantiles.
    """
    if percentiles is None:
        percentiles = [0.05, 0.25, 0.50, 0.75, 0.95]

    data = np.asarray(data, dtype=np.float64)
    n_nan = int(np.isnan(data).sum())
    valid = data[~np.isnan(data)]
    n = int(valid.size)

    if n == 0:
        result = {"mean": np.nan, "median": np.nan, "std": np.nan,
                  "skew": np.nan, "kurtosis_excess": np.nan,
                  "n": 0, "n_nan": n_nan, "min": np.nan, "max": np.nan}
        for p in percentiles:
            result[f"q_{p}"] = np.nan
        return result

    result = {
        "mean": float(np.mean(valid)),
        "median": float(np.median(valid)),
        "std": float(np.std(valid, ddof=1)) if n > 1 else 0.0,
        "skew": float(stats.skew(valid, bias=False)) if n > 2 else np.nan,
        "kurtosis_excess": float(stats.kurtosis(valid, fisher=True, bias=False)) if n > 3 else np.nan,
        "n": n,
        "n_nan": n_nan,
        "min": float(np.min(valid)),
        "max": float(np.max(valid)),
    }
    for p in percentiles:
        result[f"q_{p}"] = float(np.percentile(valid, p * 100))
    return result


def skew_kurt_robust(
    data: np.ndarray,
    bias: bool = False,
    nan_policy: Literal["propagate", "raise", "omit"] = "omit",
) -> dict[str, float]:
    """Robust skewness and excess kurtosis (Fisher-Pearson).

    Parameters
    ----------
    data : np.ndarray
        Input data.
    bias : bool
        If False, use Fisher-Pearson correction.
    nan_policy : {"propagate", "raise", "omit"}
        How to handle NaN.

    Returns
    -------
    dict with skewness and kurtosis_excess.
    """
    data = np.asarray(data, dtype=np.float64)

    if nan_policy == "raise" and np.isnan(data).any():
        raise ValueError("data contains NaN")
    elif nan_policy == "omit":
        data = data[~np.isnan(data)]

    if data.size < 3:
        return {"skewness": np.nan, "kurtosis_excess": np.nan}
    if data.size < 4:
        return {
            "skewness": float(stats.skew(data, bias=bias)),
            "kurtosis_excess": np.nan,
        }

    return {
        "skewness": float(stats.skew(data, bias=bias)),
        "kurtosis_excess": float(stats.kurtosis(data, fisher=True, bias=bias)),
    }


def kolmogorov_smirnov_test(
    sample_a: np.ndarray,
    sample_b: np.ndarray | str | None = None,
    mode: Literal["one_sample", "two_sample"] = "two_sample",
    alternative: Literal["two-sided", "less", "greater"] = "two-sided",
) -> dict[str, float]:
    """Kolmogorov-Smirnov test for distribution similarity.

    Parameters
    ----------
    sample_a : np.ndarray
        First sample.
    sample_b : np.ndarray | str | None
        Second sample (two_sample) or distribution name (one_sample).
    mode : {"one_sample", "two_sample"}
        Test mode.
    alternative : {"two-sided", "less", "greater"}
        Alternative hypothesis.

    Returns
    -------
    dict with statistic, p_value, n_a, n_b.
    """
    sample_a = np.asarray(sample_a, dtype=np.float64)
    sample_a = sample_a[~np.isnan(sample_a)]

    if mode == "two_sample":
        if sample_b is None:
            raise ValueError("sample_b required for two_sample mode")
        sample_b_arr = np.asarray(sample_b, dtype=np.float64)
        sample_b_arr = sample_b_arr[~np.isnan(sample_b_arr)]
        stat, p = stats.ks_2samp(sample_a, sample_b_arr, alternative=alternative)
        return {"statistic": float(stat), "p_value": float(p),
                "n_a": len(sample_a), "n_b": len(sample_b_arr)}
    else:  # one_sample
        if sample_b is None:
            sample_b = "norm"
        stat, p = stats.kstest(sample_a, sample_b, alternative=alternative)
        return {"statistic": float(stat), "p_value": float(p),
                "n_a": len(sample_a), "n_b": 0}


def mann_kendall_trend(
    data: np.ndarray,
    alpha: float = 0.05,
    hamed_rao_correction: bool = True,
) -> dict[str, Any]:
    """Mann-Kendall monotonic trend test with Hamed-Rao autocorrelation correction.

    Parameters
    ----------
    data : np.ndarray
        Time series data.
    alpha : float
        Significance level.
    hamed_rao_correction : bool
        Apply Hamed-Rao variance correction for autocorrelation.

    Returns
    -------
    dict with trend, p_value, tau, z_score, slope, n.
    """
    data = np.asarray(data, dtype=np.float64)
    data = data[~np.isnan(data)]
    n = len(data)

    if n < 3:
        return {"trend": "no_trend", "p_value": 1.0, "tau": 0.0,
                "z_score": 0.0, "slope": 0.0, "n": n}

    # Vectorized S statistic using broadcasting
    # S = sum_{i<j} sign(x_j - x_i)
    diff_matrix = np.subtract.outer(data, data)
    # Upper triangle (i < j): data[j] - data[i]
    s = np.sum(np.sign(-diff_matrix[np.triu_indices(n, k=1)]))

    # Kendall's tau
    tau = 2.0 * s / (n * (n - 1))

    # Variance of S
    var_s = n * (n - 1) * (2 * n + 5) / 18.0

    # Tie correction
    unique, counts = np.unique(data, return_counts=True)
    for t in counts[counts > 1]:
        var_s -= t * (t - 1) * (2 * t + 5) / 18.0

    # Hamed-Rao correction (1998): only use significant ACF lags
    if hamed_rao_correction and n > 10:
        ranks = stats.rankdata(data)
        # Compute ACF of ranks
        acf = np.zeros(n - 1)
        mean_rank = ranks.mean()
        var_rank = ((ranks - mean_rank) ** 2).sum()
        for lag in range(1, n - 1):
            cov = ((ranks[:-lag] - mean_rank) * (ranks[lag:] - mean_rank)).sum()
            acf[lag] = cov / var_rank

        # Significance test: |ACF| > 1.96/sqrt(n) at alpha=0.05
        acf_threshold = 1.96 / np.sqrt(n)
        significant_lags = np.where(np.abs(acf) > acf_threshold)[0]

        if len(significant_lags) > 0:
            correction = 0.0
            for lag in significant_lags:
                correction += (n - lag) * (n - lag - 1) * (n - lag - 2) * acf[lag]
            var_s = var_s + 2 * correction / (n * (n - 1) * (n - 2))

    # Z-score
    if s > 0:
        z = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s)
    else:
        z = 0.0

    p_value = 2 * (1 - stats.norm.cdf(abs(z)))

    # Sen's slope: vectorized
    i_idx, j_idx = np.triu_indices(n, k=1)
    slopes = (data[j_idx] - data[i_idx]) / (j_idx - i_idx)
    slope = float(np.median(slopes))

    # Determine trend
    if p_value <= alpha:
        trend = "increasing" if z > 0 else "decreasing"
    else:
        trend = "no_trend"

    return {
        "trend": trend,
        "p_value": float(p_value),
        "tau": float(tau),
        "z_score": float(z),
        "slope": slope,
        "n": n,
    }


def bayes_beta_update(
    prior_alpha: float,
    prior_beta: float,
    successes: int,
    failures: int,
    posterior_quantiles: list[float] | None = None,
) -> dict[str, float]:
    """Beta(α, β) posterior update.

    α_post = α_prior + successes
    β_post = β_prior + failures

    Parameters
    ----------
    prior_alpha, prior_beta : float
        Prior parameters (must be > 0).
    successes, failures : int
        Observed counts (must be >= 0).
    posterior_quantiles : list[float]
        Quantiles to compute from posterior.

    Returns
    -------
    dict with posterior_alpha, posterior_beta, posterior_mean, posterior_mode, and quantiles.
    """
    if prior_alpha <= 0 or prior_beta <= 0:
        raise ValueError("prior_alpha and prior_beta must be > 0")
    if successes < 0 or failures < 0:
        raise ValueError("successes and failures must be >= 0")

    if posterior_quantiles is None:
        posterior_quantiles = [0.05, 0.5, 0.95]

    a = prior_alpha + successes
    b = prior_beta + failures

    mean = a / (a + b)
    mode = (a - 1) / (a + b - 2) if (a > 1 and b > 1) else np.nan

    dist = stats.beta(a, b)
    result = {
        "posterior_alpha": float(a),
        "posterior_beta": float(b),
        "posterior_mean": float(mean),
        "posterior_mode": float(mode),
    }
    for q in posterior_quantiles:
        result[f"q_{q}"] = float(dist.ppf(q))
    return result


def brier_score_decomposed(
    forecasts: np.ndarray,
    outcomes: np.ndarray,
    n_bins: int = 10,
    method: Literal["binned", "binless"] = "binned",
) -> dict[str, float]:
    """Brier Score with Murphy 1973 three-component decomposition.

    BS = reliability - resolution + uncertainty

    Parameters
    ----------
    forecasts : np.ndarray
        Predicted probabilities in [0, 1].
    outcomes : np.ndarray
        Binary outcomes {0, 1}.
    n_bins : int
        Number of bins for decomposition.
    method : {"binned", "binless"}
        Decomposition method.

    Returns
    -------
    dict with brier_score, reliability, resolution, uncertainty, skill.
    """
    forecasts = np.asarray(forecasts, dtype=np.float64)
    outcomes = np.asarray(outcomes, dtype=np.float64)

    # Validate outcomes
    unique_outcomes = np.unique(outcomes[~np.isnan(outcomes)])
    if not np.all(np.isin(unique_outcomes, [0, 1])):
        raise ValueError("outcomes must be binary {0, 1}")

    # Clip forecasts with warning
    if np.any((forecasts < 0) | (forecasts > 1)):
        warnings.warn("forecasts outside [0,1] will be clipped", stacklevel=2)
        forecasts = np.clip(forecasts, 0, 1)

    n = len(forecasts)

    brier_score = float(np.mean((forecasts - outcomes) ** 2))
    obar = float(np.mean(outcomes))
    uncertainty = obar * (1 - obar)

    if method == "binned":
        bin_edges = np.linspace(0, 1, n_bins + 1)
        reliability = 0.0
        resolution = 0.0

        for i in range(n_bins):
            mask = (forecasts >= bin_edges[i]) & (forecasts < bin_edges[i + 1])
            if i == n_bins - 1:
                mask = (forecasts >= bin_edges[i]) & (forecasts <= bin_edges[i + 1])
            n_k = mask.sum()
            if n_k == 0:
                continue
            p_k = forecasts[mask].mean()
            obar_k = outcomes[mask].mean()
            reliability += n_k * (p_k - obar_k) ** 2
            resolution += n_k * (obar_k - obar) ** 2

        reliability /= n
        resolution /= n
    else:  # binless
        reliability = brier_score - uncertainty
        resolution = 0.0

    skill = (resolution - reliability) / uncertainty if uncertainty > 0 else 0.0

    return {
        "brier_score": brier_score,
        "reliability": float(reliability),
        "resolution": float(resolution),
        "uncertainty": float(uncertainty),
        "skill": float(skill),
    }


def pearson_spearman_corr(
    x: np.ndarray,
    y: np.ndarray,
    min_samples: int = 30,
    nan_policy: Literal["propagate", "raise", "omit"] = "omit",
) -> dict[str, float]:
    """Compute Pearson and Spearman correlation coefficients.

    Parameters
    ----------
    x, y : np.ndarray
        Input arrays.
    min_samples : int
        Minimum valid samples required.
    nan_policy : {"propagate", "raise", "omit"}
        How to handle NaN.

    Returns
    -------
    dict with pearson_r, pearson_p, spearman_r, spearman_p, n_samples.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    if nan_policy == "raise" and (np.isnan(x).any() or np.isnan(y).any()):
        raise ValueError("Input contains NaN")
    elif nan_policy == "omit":
        valid = ~(np.isnan(x) | np.isnan(y))
        x, y = x[valid], y[valid]

    n = len(x)
    if n < min_samples:
        raise ValueError(f"Only {n} valid samples, need >= {min_samples}")

    pr, pp = stats.pearsonr(x, y)
    sr, sp = stats.spearmanr(x, y)

    return {
        "pearson_r": float(pr),
        "pearson_p": float(pp),
        "spearman_r": float(sr),
        "spearman_p": float(sp),
        "n_samples": n,
    }


def kde_density(
    data: np.ndarray,
    bandwidth: Literal["silverman", "scott"] | float = "silverman",
    eval_points: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Kernel density estimation.

    Parameters
    ----------
    data : np.ndarray
        Input data.
    bandwidth : {"silverman", "scott"} or float
        Bandwidth selection method or explicit value.
    eval_points : np.ndarray | None
        Points at which to evaluate density. None = auto.

    Returns
    -------
    dict with x (eval points) and density arrays.
    """
    data = np.asarray(data, dtype=np.float64)
    data = data[~np.isnan(data)]

    if data.size < 2:
        raise ValueError("Need at least 2 data points for KDE")

    bw = bandwidth if isinstance(bandwidth, (int, float)) else bandwidth
    kde = stats.gaussian_kde(data, bw_method=bw)

    if eval_points is None:
        x_min, x_max = data.min(), data.max()
        margin = (x_max - x_min) * 0.1
        eval_points = np.linspace(x_min - margin, x_max + margin, 200)

    density = kde(eval_points)

    return {"x": eval_points, "density": density}


def correlation_batch(
    data: pd.DataFrame,
    method: Literal["pearson", "spearman"] = "pearson",
) -> pd.DataFrame:
    """Compute full correlation matrix for a DataFrame.

    Parameters
    ----------
    data : pd.DataFrame
        Input data (n_samples × m_features).
    method : {"pearson", "spearman"}
        Correlation method.

    Returns
    -------
    pd.DataFrame
        m × m correlation matrix.
    """
    if not isinstance(data, pd.DataFrame):
        raise ValueError("data must be a pandas DataFrame")
    if data.empty:
        raise ValueError("data must not be empty")
    if method not in ("pearson", "spearman"):
        raise ValueError(f"method must be 'pearson' or 'spearman', got '{method}'")

    return data.corr(method=method)


def percentile_value(
    data: np.ndarray,
    q: float,
    window: int | None = None,
    method: str = "linear",
) -> float | np.ndarray:
    """Compute the q-th percentile value from data.

    Unlike percentile_rank (which returns "where does this value rank"),
    this returns "what is the value at quantile q".

    Parameters
    ----------
    data : np.ndarray
        1-D array of values.
    q : float
        Quantile in [0, 1].
    window : int, optional
        If provided, compute rolling quantile and return array.
        If None, compute single quantile over entire data.
    method : str
        Interpolation method (passed to np.quantile).

    Returns
    -------
    float | np.ndarray
        Single quantile value, or rolling quantile array.

    References
    ----------
    .. [1] Hyndman, R.J. & Fan, Y. (1996). Sample Quantiles in Statistical Packages.
    """
    data = np.asarray(data, dtype=float)
    if not 0 <= q <= 1:
        raise ValueError(f"q must be in [0, 1], got {q}")

    if window is None:
        valid = data[np.isfinite(data)]
        if len(valid) == 0:
            return float("nan")
        return float(np.quantile(valid, q, method=method))

    # Rolling quantile
    n = len(data)
    result = np.full(n, np.nan)
    for i in range(window, n):
        seg = data[i - window: i]
        valid = seg[np.isfinite(seg)]
        if len(valid) >= 10:
            result[i] = float(np.quantile(valid, q, method=method))
    return result
