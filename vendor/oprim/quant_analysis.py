"""oprim.quant_analysis — 量化分析工具门面模块。

暴露 _quant_analysis.py 的全部公开原子函数。消费方通过
oprim.quant_analysis.<fn> 路径调用。
"""
from oprim._quant_analysis import (
    QuantAnalysisError,
    compute_pnl_from_trades,
    compute_equity_curve,
    compute_drawdown_distribution,
    compute_market_impact,
    generate_bootstrap_samples,
    compute_monte_carlo_simulation,
    compute_benchmark_metrics,
    compute_relative_performance,
    split_train_test_time_series,
    compute_portfolio_turnover,
    compute_position_churn,
    compute_risk_exposure,
    compute_position_risk,
    compute_mcmc_sample,
    compute_shapley_decomposition,
    compute_shapley_values,
    compute_herfindahl_index,
    compute_signal_crowding,
    compute_uncertainty_threshold,
)

__all__ = [
    "QuantAnalysisError",
    "compute_pnl_from_trades",
    "compute_equity_curve",
    "compute_drawdown_distribution",
    "compute_market_impact",
    "generate_bootstrap_samples",
    "compute_monte_carlo_simulation",
    "compute_benchmark_metrics",
    "compute_relative_performance",
    "split_train_test_time_series",
    "compute_portfolio_turnover",
    "compute_position_churn",
    "compute_risk_exposure",
    "compute_position_risk",
    "compute_mcmc_sample",
    "compute_shapley_decomposition",
    "compute_shapley_values",
    "compute_herfindahl_index",
    "compute_signal_crowding",
    "compute_uncertainty_threshold",
]
