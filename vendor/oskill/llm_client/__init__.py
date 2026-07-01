"""LLM API client subpackage — DeepSeek (Phase 3 P14)."""

from oskill.llm_client.deepseek import call as deepseek_call
from oskill.llm_client.exceptions import (
    LLMAPIError,
    LLMRateLimit,
    LLMTimeout,
    LLMUnavailable,
)

__all__ = [
    "deepseek_call",
    "LLMUnavailable",
    "LLMRateLimit",
    "LLMAPIError",
    "LLMTimeout",
]
