"""Signal ensemble submodule."""

from oskill.signals.aggregation import weighted_signal_aggregation
from oskill.signals.ensemble import signal_ensemble
from oskill.signals.forward_returns import aggregate_signal_returns

__all__ = ["signal_ensemble", "weighted_signal_aggregation", "aggregate_signal_returns"]
