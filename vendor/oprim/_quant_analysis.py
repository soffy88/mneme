"""Quantitative analysis oprims — backtest, risk, portfolio computation primitives."""
from __future__ import annotations

import math
import random
from typing import Any


class QuantAnalysisError(Exception):
    """Raised when a quant analysis oprim fails."""


def compute_pnl_from_trades(*, trades: list[dict]) -> list[float]:
    """Compute PnL series from trade list.

    Example:
        >>> compute_pnl_from_trades(trades=[{"entry": 100, "exit": 110, "size": 1}])
        [10.0]
    """
    return [t.get("size", 1) * (t.get("exit", 0) - t.get("entry", 0)) for t in trades]


def compute_equity_curve(*, initial_capital: float, pnl_series: list[float]) -> list[float]:
    """Build equity curve from initial capital and PnL series.

    Example:
        >>> compute_equity_curve(initial_capital=10000, pnl_series=[100, -50, 200])
        [10000, 10100, 10050, 10250]
    """
    curve = [initial_capital]
    for pnl in pnl_series:
        curve.append(curve[-1] + pnl)
    return curve


def compute_drawdown_distribution(*, equity_curve: list[float]) -> dict:
    """Compute drawdown distribution statistics.

    Example:
        >>> compute_drawdown_distribution(equity_curve=[100, 110, 105, 115])
        {'max_dd': 0.0455, 'avg_dd': ..., 'dd_count': 1}
    """
    if len(equity_curve) < 2:
        return {"max_dd": 0, "avg_dd": 0, "dd_count": 0}
    peak = equity_curve[0]
    drawdowns = []
    current_dd = 0
    for v in equity_curve:
        peak = max(peak, v)
        dd = (peak - v) / peak if peak > 0 else 0
        if dd > 0:
            current_dd = max(current_dd, dd)
        elif current_dd > 0:
            drawdowns.append(current_dd)
            current_dd = 0
    if current_dd > 0:
        drawdowns.append(current_dd)
    max_dd = max(drawdowns) if drawdowns else 0
    avg_dd = sum(drawdowns) / len(drawdowns) if drawdowns else 0
    return {"max_dd": round(max_dd, 6), "avg_dd": round(avg_dd, 6), "dd_count": len(drawdowns)}


def compute_market_impact(*, order_size: float, avg_daily_volume: float, volatility: float) -> float:
    """Estimate market impact using square-root model.

    Example:
        >>> compute_market_impact(order_size=1000, avg_daily_volume=100000, volatility=0.02)
        0.002
    """
    if avg_daily_volume <= 0:
        return 0.0
    participation = order_size / avg_daily_volume
    return round(volatility * math.sqrt(participation), 6)


def generate_bootstrap_samples(*, data: list[float], n_samples: int = 1000, sample_size: int | None = None) -> list[list[float]]:
    """Generate bootstrap resamples from data.

    Example:
        >>> len(generate_bootstrap_samples(data=[1,2,3], n_samples=10))
        10
    """
    size = sample_size or len(data)
    return [random.choices(data, k=size) for _ in range(n_samples)]


def compute_monte_carlo_simulation(*, mean_return: float, std_return: float, n_periods: int = 252, n_paths: int = 1000) -> dict:
    """Run Monte Carlo simulation for return paths.

    Example:
        >>> r = compute_monte_carlo_simulation(mean_return=0.001, std_return=0.02, n_periods=30, n_paths=100)
        >>> len(r['terminal_values']) == 100
        True
    """
    terminals = []
    for _ in range(n_paths):
        value = 1.0
        for _ in range(n_periods):
            value *= 1 + random.gauss(mean_return, std_return)
        terminals.append(value)
    return {
        "terminal_values": [round(t, 6) for t in terminals],
        "mean_terminal": round(sum(terminals) / n_paths, 6),
        "p5": round(sorted(terminals)[int(n_paths * 0.05)], 6),
        "p95": round(sorted(terminals)[int(n_paths * 0.95)], 6),
    }


def compute_benchmark_metrics(*, strategy_returns: list[float], benchmark_returns: list[float]) -> dict:
    """Compute strategy vs benchmark relative metrics.

    Example:
        >>> compute_benchmark_metrics(strategy_returns=[0.01, 0.02], benchmark_returns=[0.005, 0.01])
        {'alpha': ..., 'beta': ..., 'tracking_error': ...}
    """
    n = min(len(strategy_returns), len(benchmark_returns))
    if n < 2:
        return {"alpha": 0, "beta": 0, "tracking_error": 0, "info_ratio": 0}
    s, b = strategy_returns[:n], benchmark_returns[:n]
    s_mean = sum(s) / n
    b_mean = sum(b) / n
    cov = sum((s[i] - s_mean) * (b[i] - b_mean) for i in range(n)) / (n - 1)
    b_var = sum((b[i] - b_mean) ** 2 for i in range(n)) / (n - 1)
    beta = cov / b_var if b_var > 0 else 0
    alpha = s_mean - beta * b_mean
    excess = [s[i] - b[i] for i in range(n)]
    te = (sum((e - sum(excess) / n) ** 2 for e in excess) / (n - 1)) ** 0.5
    ir = (sum(excess) / n) / te if te > 0 else 0
    return {"alpha": round(alpha, 6), "beta": round(beta, 4), "tracking_error": round(te, 6), "info_ratio": round(ir, 4)}


def compute_relative_performance(*, strategy_curve: list[float], benchmark_curve: list[float]) -> list[float]:
    """Compute relative performance (strategy / benchmark).

    Example:
        >>> compute_relative_performance(strategy_curve=[100, 110], benchmark_curve=[100, 105])
        [1.0, 1.0476]
    """
    n = min(len(strategy_curve), len(benchmark_curve))
    return [round(strategy_curve[i] / benchmark_curve[i], 6) if benchmark_curve[i] != 0 else 1.0 for i in range(n)]


def split_train_test_time_series(*, data: list, train_ratio: float = 0.7) -> tuple[list, list]:
    """Split time series into train/test preserving temporal order.

    Example:
        >>> split_train_test_time_series(data=[1,2,3,4,5], train_ratio=0.6)
        ([1, 2, 3], [4, 5])
    """
    split_idx = int(len(data) * train_ratio)
    return data[:split_idx], data[split_idx:]


def compute_portfolio_turnover(*, weights_before: dict[str, float], weights_after: dict[str, float]) -> float:
    """Compute portfolio turnover (sum of absolute weight changes / 2).

    Example:
        >>> compute_portfolio_turnover(weights_before={"A": 0.5, "B": 0.5}, weights_after={"A": 0.7, "B": 0.3})
        0.2
    """
    all_assets = set(weights_before) | set(weights_after)
    total_change = sum(abs(weights_after.get(a, 0) - weights_before.get(a, 0)) for a in all_assets)
    return round(total_change / 2, 6)


def compute_position_churn(*, position_history: list[dict[str, float]]) -> float:
    """Compute average position churn across rebalance periods.

    Example:
        >>> compute_position_churn(position_history=[{"A": 0.5}, {"A": 0.7}, {"A": 0.4}])
        0.15
    """
    if len(position_history) < 2:
        return 0.0
    turnovers = []
    for i in range(1, len(position_history)):
        t = compute_portfolio_turnover(weights_before=position_history[i - 1], weights_after=position_history[i])
        turnovers.append(t)
    return round(sum(turnovers) / len(turnovers), 6)


def compute_risk_exposure(*, positions: dict[str, float], factor_loadings: dict[str, dict[str, float]]) -> dict[str, float]:
    """Compute portfolio risk factor exposures.

    Example:
        >>> compute_risk_exposure(positions={"BTC": 0.6, "ETH": 0.4}, factor_loadings={"BTC": {"market": 1.2}, "ETH": {"market": 1.5}})
        {'market': 1.32}
    """
    factors: dict[str, float] = {}
    for asset, weight in positions.items():
        loadings = factor_loadings.get(asset, {})
        for factor, loading in loadings.items():
            factors[factor] = factors.get(factor, 0) + weight * loading
    return {k: round(v, 6) for k, v in factors.items()}


def compute_position_risk(*, position_size: float, volatility: float, confidence: float = 0.95) -> dict:
    """Compute position-level VaR and expected shortfall.

    Example:
        >>> compute_position_risk(position_size=10000, volatility=0.02)
        {'var_95': 329.0, 'es_95': 412.0}
    """
    z = 1.645 if confidence == 0.95 else 2.326 if confidence == 0.99 else 1.282
    var = position_size * volatility * z
    es = var * 1.25  # simplified ES approximation
    return {"var_95": round(var, 2), "es_95": round(es, 2)}


def compute_mcmc_sample(*, log_posterior_fn: Any, initial: list[float], n_samples: int = 1000, step_size: float = 0.1) -> list[list[float]]:
    """Generate MCMC samples using Metropolis-Hastings.

    Example:
        >>> samples = compute_mcmc_sample(log_posterior_fn=lambda x: -sum(xi**2 for xi in x), initial=[0.0], n_samples=100)
        >>> len(samples) == 100
        True
    """
    current = list(initial)
    dim = len(current)
    samples = []
    current_lp = log_posterior_fn(current)
    for _ in range(n_samples):
        proposal = [c + random.gauss(0, step_size) for c in current]
        proposal_lp = log_posterior_fn(proposal)
        if math.log(random.random() + 1e-300) < proposal_lp - current_lp:
            current = proposal
            current_lp = proposal_lp
        samples.append(list(current))
    return samples


def compute_shapley_decomposition(*, contributions: dict[str, float], total: float) -> dict[str, float]:
    """Compute Shapley-value-style attribution (simplified marginal contribution).

    Example:
        >>> compute_shapley_decomposition(contributions={"A": 30, "B": 20, "C": 10}, total=72)
        {'A': 0.417, 'B': 0.278, 'C': 0.139, 'residual': 0.167}
    """
    if total == 0:
        return {k: 0.0 for k in contributions}
    result = {k: round(v / total, 4) for k, v in contributions.items()}
    explained = sum(result.values())
    result["residual"] = round(1.0 - explained, 4)
    return result


def compute_shapley_values(
    *,
    features: dict[str, float],
    aggregate_fn,
    baseline_features: dict[str, float] | None = None,
    method: str = "monte_carlo",
    n_samples: int = 2000,
    seed: int = 42,
) -> dict[str, float]:
    """True (non-linear) Shapley value decomposition over an aggregation function.

    Unlike compute_shapley_decomposition (proportional split, kept as fallback),
    this computes real marginal contributions: for each feature, the average
    change in aggregate_fn output when that feature is present vs absent across
    coalitions. Works for non-linear aggregate_fn (e.g. geometric mean fusion).

    Args:
        features: {dim: value} — raw per-dimension feature values.
        aggregate_fn: callable(dict[str, float]) -> float. The (possibly
            non-linear) fusion function. Absent dimensions are replaced by the
            corresponding baseline value when forming a coalition.
        baseline_features: {dim: value} representing "absent" state per dim.
            Defaults to 0.0 for every dim. baseline output = aggregate_fn(all-absent).
        method: "monte_carlo" (sampled permutations) or "exact" (2^n, n<=12).
        n_samples: permutations sampled in monte_carlo mode.
        seed: RNG seed for determinism (same input → same output).

    Returns:
        {dim: shapley_value, ..., "baseline": float, "residual": float}
        where sum(shapley_values) + baseline + residual == aggregate_fn(features).
        residual captures numerical/sampling slack (≈0 for exact, small for MC).

    Raises:
        QuantAnalysisError: if features empty, aggregate_fn not callable, or
            method="exact" with n>12 (combinatorial blowup).

    Example:
        >>> agg = lambda d: (d.get("a",0)*d.get("b",0)) ** 0.5  # non-linear
        >>> sv = compute_shapley_values(features={"a":4.0,"b":9.0}, aggregate_fn=agg)
        >>> round(sv["a"] + sv["b"] + sv["baseline"] + sv["residual"], 6) == round(agg({"a":4.0,"b":9.0}),6)
        True
    """
    import random as _random

    if not features:
        raise QuantAnalysisError("features must be non-empty")
    if not callable(aggregate_fn):
        raise QuantAnalysisError("aggregate_fn must be callable")

    dims = list(features.keys())
    n = len(dims)
    base = baseline_features or {d: 0.0 for d in dims}

    def _coalition_value(present: set[str]) -> float:
        """aggregate_fn with present dims = real value, absent = baseline."""
        coalition = {d: (features[d] if d in present else base.get(d, 0.0)) for d in dims}
        return float(aggregate_fn(coalition))

    baseline_output = _coalition_value(set())
    full_output = _coalition_value(set(dims))

    shapley: dict[str, float] = {d: 0.0 for d in dims}

    if method == "exact":
        if n > 12:
            raise QuantAnalysisError(
                f"exact method infeasible for n={n} (2^{n} coalitions); use monte_carlo"
            )
        from itertools import permutations as _perms
        all_perms = list(_perms(dims))
        for perm in all_perms:
            present: set[str] = set()
            prev = _coalition_value(present)
            for d in perm:
                present.add(d)
                cur = _coalition_value(present)
                shapley[d] += (cur - prev)
                prev = cur
        for d in dims:
            shapley[d] /= len(all_perms)
    elif method == "monte_carlo":
        rng = _random.Random(seed)
        for _ in range(n_samples):
            perm = dims[:]
            rng.shuffle(perm)
            present = set()
            prev = _coalition_value(present)
            for d in perm:
                present.add(d)
                cur = _coalition_value(present)
                shapley[d] += (cur - prev)
                prev = cur
        for d in dims:
            shapley[d] /= n_samples
    else:
        raise QuantAnalysisError(f"unknown method: {method!r} (use 'monte_carlo' or 'exact')")

    result = {d: round(shapley[d], 6) for d in dims}
    result["baseline"] = round(baseline_output, 6)
    # residual = full - baseline - sum(shapley); ≈0 exact, small sampling slack MC
    residual = full_output - baseline_output - sum(shapley.values())
    result["residual"] = round(residual, 6)
    return result


def compute_herfindahl_index(*, weights: dict[str, float]) -> float:
    """Compute Herfindahl-Hirschman Index (concentration measure).

    Example:
        >>> compute_herfindahl_index(weights={"A": 0.5, "B": 0.3, "C": 0.2})
        0.38
    """
    return round(sum(w**2 for w in weights.values()), 6)


def compute_signal_crowding(*, signal_counts: dict[str, int], total_participants: int) -> dict:
    """Measure signal crowding (how many participants share same signal).

    Example:
        >>> compute_signal_crowding(signal_counts={"buy": 80, "sell": 20}, total_participants=100)
        {'crowding_ratio': 0.8, 'dominant': 'buy', 'hhi': 0.68}
    """
    if total_participants <= 0:
        return {"crowding_ratio": 0, "dominant": "", "hhi": 0}
    ratios = {k: v / total_participants for k, v in signal_counts.items()}
    dominant = max(ratios, key=ratios.get)  # type: ignore[arg-type]
    hhi = sum(r**2 for r in ratios.values())
    return {"crowding_ratio": round(ratios[dominant], 4), "dominant": dominant, "hhi": round(hhi, 4)}


def compute_uncertainty_threshold(*, uncertainties: list[float], percentile: float = 0.9) -> float:
    """Compute adaptive uncertainty threshold from historical distribution.

    Example:
        >>> compute_uncertainty_threshold(uncertainties=[0.1, 0.2, 0.3, 0.4, 0.5])
        0.46
    """
    if not uncertainties:
        return 0.5
    sorted_u = sorted(uncertainties)
    idx = min(int(len(sorted_u) * percentile), len(sorted_u) - 1)
    return round(sorted_u[idx], 6)
