"""Risk primitives submodule."""

from oprim.risk.cvar import cvar
from oprim.risk.dispersion import mean_deviation

__all__ = ["cvar", "mean_deviation"]
