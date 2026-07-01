"""LLM client exception hierarchy.

LLMUnavailable is the base class — caller catches this to handle all retriable
failures uniformly. Subclasses provide diagnostic granularity for metrics/audit.
"""


class LLMUnavailable(Exception):
    """Base class for all LLM API failures.

    Caller (e.g. omodul.strategies.tradingagents_v1) should:
    - log + skip current trigger
    - publish signal_dropped event with reason=str(this exception)
    - NOT fallback to classic strategy (Cap 10 §2.5)
    """


class LLMRateLimit(LLMUnavailable):
    """HTTP 429 from API. Caller should not retry immediately."""


class LLMAPIError(LLMUnavailable):
    """Non-2xx response other than 429 (e.g. 5xx, 400 bad request)."""


class LLMTimeout(LLMUnavailable):
    """Connection / read timeout."""
