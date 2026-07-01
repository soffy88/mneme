"""Market making submodule (Avellaneda-Stoikov + Cartea-Jaimungal)."""

from oskill.market_making.avellaneda_stoikov import avellaneda_stoikov_quotes
from oskill.market_making.cartea_jaimungal import cartea_jaimungal_optimal_quotes

__all__ = ["avellaneda_stoikov_quotes", "cartea_jaimungal_optimal_quotes"]
