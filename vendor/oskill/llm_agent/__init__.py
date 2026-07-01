"""LLM agent subpackage — bull/bear/referee roles (Phase 3 P15)."""

from oskill.llm_agent.bear_analyst import bear_analyst
from oskill.llm_agent.bull_analyst import bull_analyst
from oskill.llm_agent.referee import referee

__all__ = ["bull_analyst", "bear_analyst", "referee"]
