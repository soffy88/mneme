"""Performance metrics submodule."""
from oprim.performance.annualization import cagr
from oprim.performance.cumulative import cumulative_returns

__all__ = ["cumulative_returns", "cagr"]
