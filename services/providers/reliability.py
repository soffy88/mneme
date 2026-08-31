"""Unified reliability, budget, and privacy-safe observability wrapper.

All server-side LLM/VLM provider calls pass through this module.  Provider
completion requests are side-effect-free from Mneme's perspective, so they may
be retried only when the caller explicitly opts into ``retryable=True``.  The
wrapper never writes learning state and a failed call raises a typed error so
the surrounding service can select its existing deterministic/degraded path.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from obase.provider_timeout import ProviderTimeoutPolicy, provider_timeout_policy


class ProviderExecutionError(RuntimeError):
    """Safe provider failure; ``error_class`` contains no provider payload."""

    def __init__(self, error_class: str, *, retryable: bool = False) -> None:
        super().__init__(f"provider execution failed: {error_class}")
        self.error_class = error_class
        self.retryable = retryable


class ProviderCircuitOpenError(ProviderExecutionError):
    def __init__(self) -> None:
        super().__init__("circuit_open", retryable=False)


class ProviderBulkheadError(ProviderExecutionError):
    def __init__(self) -> None:
        super().__init__("bulkhead_saturated", retryable=False)


class ProviderRateLimitError(ProviderExecutionError):
    def __init__(self) -> None:
        super().__init__("rate_limited", retryable=False)


class ProviderBudgetError(ProviderExecutionError):
    def __init__(self, budget: str) -> None:
        super().__init__(f"{budget}_budget_exceeded", retryable=False)


class ProviderMalformedResponseError(ProviderExecutionError):
    def __init__(self) -> None:
        super().__init__("malformed_response", retryable=False)


@dataclass(frozen=True, slots=True)
class ProviderReliabilityConfig:
    timeout: ProviderTimeoutPolicy
    # A logical request has one hard wall-clock deadline, including retries and
    # backoff.  This keeps a provider outage from pinning a worker for minutes.
    total_timeout_seconds: float = 90.0
    max_retries: int = 2
    backoff_base_seconds: float = 0.25
    backoff_max_seconds: float = 2.0
    jitter_seconds: float = 0.25
    circuit_failure_threshold: int = 3
    circuit_recovery_seconds: float = 30.0
    bulkhead_size: int = 8
    bulkhead_wait_seconds: float = 0.05
    requests_per_minute: int = 60
    requests_per_window: int = 1000
    input_tokens_per_window: int = 1_000_000
    output_tokens_per_window: int = 250_000
    cost_usd_per_window: float = 25.0
    input_cost_per_1k_usd: float = 0.0
    output_cost_per_1k_usd: float = 0.0
    window_seconds: float = 86_400.0

    def __post_init__(self) -> None:
        """Keep programmatic configuration subject to the same hard limits."""

        if not 0 < self.timeout.connect_seconds <= 15:
            raise ValueError("provider connect timeout must be in (0, 15] seconds")
        if not 0 < self.timeout.read_seconds <= 120:
            raise ValueError("provider read timeout must be in (0, 120] seconds")
        if not 0 < self.total_timeout_seconds <= 120:
            raise ValueError("provider total timeout must be in (0, 120] seconds")
        if not 0 <= self.max_retries <= 2:
            raise ValueError("provider max retries must be in [0, 2]")
        if not 0 <= self.backoff_base_seconds <= 2:
            raise ValueError("provider backoff base must be in [0, 2] seconds")
        if not 0 <= self.backoff_max_seconds <= 10:
            raise ValueError("provider backoff max must be in [0, 10] seconds")
        if not 0 <= self.jitter_seconds <= 2:
            raise ValueError("provider backoff jitter must be in [0, 2] seconds")
        if self.circuit_failure_threshold < 1:
            raise ValueError("provider circuit threshold must be positive")
        if not 0 < self.circuit_recovery_seconds <= 300:
            raise ValueError("provider circuit recovery must be in (0, 300] seconds")
        if self.bulkhead_size < 1:
            raise ValueError("provider bulkhead size must be positive")
        if self.bulkhead_wait_seconds < 0:
            raise ValueError("provider bulkhead wait must be non-negative")
        if self.requests_per_minute < 1 or self.requests_per_window < 1:
            raise ValueError("provider request budgets must be positive")
        if self.input_tokens_per_window < 1 or self.output_tokens_per_window < 1:
            raise ValueError("provider token budgets must be positive")
        if self.cost_usd_per_window <= 0 or self.window_seconds <= 0:
            raise ValueError("provider cost/window budgets must be positive")
        if self.input_cost_per_1k_usd < 0 or self.output_cost_per_1k_usd < 0:
            raise ValueError("provider token prices must be non-negative")

    @classmethod
    def from_env(cls) -> "ProviderReliabilityConfig":
        """Load bounded configuration; malformed values use safe defaults."""

        def integer(name: str, default: int, maximum: int) -> int:
            try:
                value = int(os.environ.get(name, ""))
            except ValueError:
                return default
            return max(0, min(value, maximum))

        def positive_float(name: str, default: float, maximum: float) -> float:
            try:
                value = float(os.environ.get(name, ""))
            except ValueError:
                return default
            if value <= 0:
                return default
            return min(value, maximum)

        def nonnegative_float(name: str, default: float, maximum: float) -> float:
            try:
                value = float(os.environ.get(name, ""))
            except ValueError:
                return default
            if value < 0:
                return default
            return min(value, maximum)

        return cls(
            timeout=provider_timeout_policy(),
            total_timeout_seconds=positive_float(
                "MNEME_PROVIDER_TOTAL_TIMEOUT_SECONDS", 90.0, 120.0
            ),
            max_retries=integer("MNEME_PROVIDER_MAX_RETRIES", 2, 2),
            backoff_base_seconds=positive_float(
                "MNEME_PROVIDER_BACKOFF_BASE_SECONDS", 0.25, 2.0
            ),
            backoff_max_seconds=positive_float(
                "MNEME_PROVIDER_BACKOFF_MAX_SECONDS", 2.0, 10.0
            ),
            jitter_seconds=nonnegative_float(
                "MNEME_PROVIDER_BACKOFF_JITTER_SECONDS", 0.25, 2.0
            ),
            circuit_failure_threshold=integer(
                "MNEME_PROVIDER_CIRCUIT_FAILURE_THRESHOLD", 3, 10
            ),
            circuit_recovery_seconds=positive_float(
                "MNEME_PROVIDER_CIRCUIT_RECOVERY_SECONDS", 30.0, 300.0
            ),
            bulkhead_size=integer("MNEME_PROVIDER_BULKHEAD_SIZE", 8, 32) or 1,
            bulkhead_wait_seconds=nonnegative_float(
                "MNEME_PROVIDER_BULKHEAD_WAIT_SECONDS", 0.05, 0.5
            ),
            requests_per_minute=integer(
                "MNEME_PROVIDER_RATE_LIMIT_RPM", 60, 1000
            )
            or 1,
            requests_per_window=integer(
                "MNEME_PROVIDER_REQUEST_BUDGET", 1000, 100_000
            )
            or 1,
            input_tokens_per_window=integer(
                "MNEME_PROVIDER_INPUT_TOKEN_BUDGET", 1_000_000, 10_000_000
            )
            or 1,
            output_tokens_per_window=integer(
                "MNEME_PROVIDER_OUTPUT_TOKEN_BUDGET", 250_000, 10_000_000
            )
            or 1,
            cost_usd_per_window=positive_float(
                "MNEME_PROVIDER_COST_BUDGET_USD", 25.0, 10_000.0
            ),
            input_cost_per_1k_usd=nonnegative_float(
                "MNEME_PROVIDER_INPUT_COST_PER_1K_USD", 0.0, 10_000.0
            ),
            output_cost_per_1k_usd=nonnegative_float(
                "MNEME_PROVIDER_OUTPUT_COST_PER_1K_USD", 0.0, 10_000.0
            ),
        )


@dataclass(slots=True)
class _WindowBudget:
    started_at: float
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class ReliableProvider:
    """One provider-neutral async execution contract for LLM and VLM calls."""

    def __init__(
        self,
        caller: Callable[..., Awaitable[dict[str, Any]]],
        *,
        provider: str,
        model: str,
        kind: str,
        config: ProviderReliabilityConfig | None = None,
        retryable: bool = False,
    ) -> None:
        self.caller = caller
        self.provider = _safe_label(provider, "unknown")
        self.model = _safe_label(model, "unknown")
        self.kind = kind if kind in {"llm", "vlm"} else "llm"
        self.config = config or ProviderReliabilityConfig.from_env()
        self.retryable = retryable
        self._semaphore = asyncio.Semaphore(self.config.bulkhead_size)
        self._state_lock = threading.Lock()
        self._consecutive_failures = 0
        self._circuit_state = "closed"
        self._opened_at = 0.0
        self._half_open_probe = False
        self._rate_timestamps: deque[float] = deque()
        self._budget = _WindowBudget(started_at=time.monotonic())

    def __getattr__(self, name: str) -> Any:
        # Preserve provider-specific read-only metadata for existing callers.
        return getattr(self.caller, name)

    async def __call__(self, **kwargs: Any) -> dict[str, Any]:
        started_at = time.monotonic()
        deadline = started_at + self.config.total_timeout_seconds
        try:
            self._check_circuit()
        except ProviderExecutionError as exc:
            self._record_rejection(exc, elapsed_seconds=0.0)
            raise
        acquired = False
        attempts = 0
        try:
            try:
                wait_seconds = min(
                    self.config.bulkhead_wait_seconds,
                    max(0.0, deadline - time.monotonic()),
                )
                await asyncio.wait_for(
                    self._semaphore.acquire(),
                    timeout=wait_seconds,
                )
                acquired = True
            except asyncio.TimeoutError as exc:
                error = ProviderBulkheadError()
                self._record_rejection(
                    error, elapsed_seconds=time.monotonic() - started_at
                )
                self._reset_half_open_after_rejection()
                raise error from exc

            while True:
                attempts += 1
                usage = {"input_tokens": 0, "output_tokens": 0}
                cost = 0.0
                attempt_started = time.monotonic()
                provider_attempted = False
                try:
                    # Count every actual provider attempt.  A retry must not
                    # bypass the request/rate budget of the logical caller.
                    self._reserve_request()
                    provider_attempted = True
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    result = await asyncio.wait_for(
                        self.caller(**kwargs),
                        timeout=min(self.config.timeout.total_seconds, remaining),
                    )
                    normalized = self._validate_result(result)
                    usage = _usage_from_result(normalized)
                    cost = _cost_from_result(normalized, usage, self.config)
                    self._reserve_usage(usage, cost)
                    self._record_success(
                        elapsed_seconds=time.monotonic() - attempt_started,
                        usage=usage,
                        cost_usd=cost,
                    )
                    return normalized
                except asyncio.TimeoutError:
                    final_error = ProviderExecutionError("timeout", retryable=True)
                    self._record_attempt_error(final_error)
                except Exception as exc:  # noqa: BLE001 - classification below
                    final_error = _classify_exception(exc)
                    self._record_attempt_error(final_error)

                if not self._should_retry(final_error, attempts, deadline):
                    self._record_final_failure(
                        final_error,
                        elapsed_seconds=time.monotonic() - attempt_started,
                        provider_attempted=provider_attempted,
                        usage=usage,
                        cost_usd=cost,
                    )
                    raise final_error
                if provider_attempted:
                    _record_provider_result(
                        self.provider,
                        self.model,
                        outcome=final_error.error_class,
                        elapsed_seconds=time.monotonic() - attempt_started,
                        input_tokens=usage["input_tokens"],
                        output_tokens=usage["output_tokens"],
                        cost_usd=cost,
                    )
                await self._backoff(attempts, deadline)
        finally:
            if acquired:
                self._semaphore.release()

    def circuit_state(self) -> str:
        with self._state_lock:
            return self._circuit_state

    def _check_circuit(self) -> None:
        now = time.monotonic()
        with self._state_lock:
            if self._circuit_state == "open":
                if now - self._opened_at < self.config.circuit_recovery_seconds:
                    _record_circuit(self.provider, self.model, "open")
                    raise ProviderCircuitOpenError()
                if self._half_open_probe:
                    raise ProviderCircuitOpenError()
                self._half_open_probe = True
                self._circuit_state = "half_open"
            elif self._circuit_state == "half_open" and self._half_open_probe:
                _record_circuit(self.provider, self.model, "half_open")
                raise ProviderCircuitOpenError()
            _record_circuit(self.provider, self.model, self._circuit_state)

    def _record_attempt_error(self, error: ProviderExecutionError) -> None:
        _record_provider_error(self.provider, error.error_class)
        if error.error_class == "timeout" or error.error_class.endswith("_timeout"):
            _record_provider_timeout(self.provider)

    def _record_success(
        self, *, elapsed_seconds: float, usage: dict[str, int], cost_usd: float
    ) -> None:
        with self._state_lock:
            self._consecutive_failures = 0
            self._circuit_state = "closed"
            self._half_open_probe = False
        _record_provider_result(
            self.provider,
            self.model,
            outcome="success",
            elapsed_seconds=elapsed_seconds,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cost_usd=cost_usd,
        )
        _record_circuit(self.provider, self.model, "closed")

    def _record_final_failure(
        self,
        error: ProviderExecutionError,
        *,
        elapsed_seconds: float,
        provider_attempted: bool,
        usage: dict[str, int] | None = None,
        cost_usd: float = 0.0,
    ) -> None:
        with self._state_lock:
            if not isinstance(
                error,
                (ProviderBulkheadError, ProviderRateLimitError, ProviderBudgetError,
                 ProviderCircuitOpenError),
            ):
                self._consecutive_failures += 1
                threshold = max(1, self.config.circuit_failure_threshold)
                if (
                    self._circuit_state == "half_open"
                    or self._consecutive_failures >= threshold
                ):
                    self._circuit_state = "open"
                    self._opened_at = time.monotonic()
            self._half_open_probe = False
            state = self._circuit_state
        if provider_attempted:
            _record_provider_result(
                self.provider,
                self.model,
                outcome=error.error_class,
                elapsed_seconds=elapsed_seconds,
                input_tokens=(usage or {}).get("input_tokens", 0),
                output_tokens=(usage or {}).get("output_tokens", 0),
                cost_usd=cost_usd,
            )
        _record_circuit(self.provider, self.model, state)

    def _should_retry(
        self, error: ProviderExecutionError, attempts: int, deadline: float
    ) -> bool:
        return (
            self.retryable
            and error.retryable
            and attempts <= self.config.max_retries
            and time.monotonic() < deadline
        )

    async def _backoff(self, attempts: int, deadline: float) -> None:
        exponent = min(attempts - 1, 8)
        delay = min(
            self.config.backoff_max_seconds,
            self.config.backoff_base_seconds * (2**exponent),
        )
        delay += random.uniform(0.0, self.config.jitter_seconds)
        await asyncio.sleep(min(delay, max(0.0, deadline - time.monotonic())))

    def _reserve_request(self) -> None:
        now = time.monotonic()
        with self._state_lock:
            self._reset_budget_if_needed(now)
            while self._rate_timestamps and now - self._rate_timestamps[0] >= 60:
                self._rate_timestamps.popleft()
            if len(self._rate_timestamps) >= self.config.requests_per_minute:
                raise ProviderRateLimitError()
            if self._budget.requests >= self.config.requests_per_window:
                raise ProviderBudgetError("request")
            self._rate_timestamps.append(now)
            self._budget.requests += 1

    def _record_rejection(
        self, error: ProviderExecutionError, *, elapsed_seconds: float
    ) -> None:
        """Record a local policy rejection without tripping the provider breaker."""

        _record_provider_error(self.provider, error.error_class)
        _record_circuit(self.provider, self.model, self.circuit_state())

    def _reset_half_open_after_rejection(self) -> None:
        with self._state_lock:
            if self._circuit_state == "half_open":
                self._circuit_state = "open"
                self._opened_at = time.monotonic()
                self._half_open_probe = False

    def _reserve_usage(self, usage: dict[str, int], cost_usd: float) -> None:
        with self._state_lock:
            self._reset_budget_if_needed(time.monotonic())
            if (
                self._budget.input_tokens + usage["input_tokens"]
                > self.config.input_tokens_per_window
            ):
                raise ProviderBudgetError("input_token")
            if (
                self._budget.output_tokens + usage["output_tokens"]
                > self.config.output_tokens_per_window
            ):
                raise ProviderBudgetError("output_token")
            if self._budget.cost_usd + cost_usd > self.config.cost_usd_per_window:
                raise ProviderBudgetError("cost")
            self._budget.input_tokens += usage["input_tokens"]
            self._budget.output_tokens += usage["output_tokens"]
            self._budget.cost_usd += cost_usd

    def _reset_budget_if_needed(self, now: float) -> None:
        if now - self._budget.started_at >= self.config.window_seconds:
            self._budget = _WindowBudget(started_at=now)

    @staticmethod
    def _validate_result(result: Any) -> dict[str, Any]:
        if not isinstance(result, dict) or "content" not in result:
            raise ProviderMalformedResponseError()
        if not isinstance(result["content"], (str, dict, list)):
            raise ProviderMalformedResponseError()
        if isinstance(result["content"], list) and not all(
            isinstance(block, dict) for block in result["content"]
        ):
            raise ProviderMalformedResponseError()
        usage = result.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise ProviderMalformedResponseError()
        # Return a shallow copy so callers cannot mutate wrapper state.
        return dict(result)


def wrap_provider(
    caller: Callable[..., Awaitable[dict[str, Any]]],
    *,
    provider: str,
    model: str | None = None,
    kind: str = "llm",
    retryable: bool = False,
    config: ProviderReliabilityConfig | None = None,
) -> ReliableProvider:
    """Wrap a provider exactly once while preserving model metadata."""

    if isinstance(caller, ReliableProvider):
        return caller
    return ReliableProvider(
        caller,
        provider=provider,
        model=model or str(getattr(caller, "model", "unknown")),
        kind=kind,
        retryable=retryable,
        config=config,
    )


def provider_error_class(exc: BaseException) -> str:
    """Expose only a bounded classification for service fallback paths."""

    if isinstance(exc, ProviderExecutionError):
        return exc.error_class
    return _classify_exception(exc).error_class


def reset_reliability_metrics() -> None:
    """Reset wrapper-local metrics and state for deterministic tests."""

    from services.observability import reset_provider_metrics

    reset_provider_metrics()


def _classify_exception(exc: BaseException) -> ProviderExecutionError:
    if isinstance(exc, ProviderExecutionError):
        return exc
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ProviderExecutionError("timeout", retryable=True)
    try:
        import httpx

        if isinstance(exc, httpx.ConnectTimeout):
            return ProviderExecutionError("connect_timeout", retryable=True)
        if isinstance(exc, httpx.ReadTimeout):
            return ProviderExecutionError("read_timeout", retryable=True)
        if isinstance(exc, httpx.TimeoutException):
            return ProviderExecutionError("timeout", retryable=True)
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status == 429:
                return ProviderExecutionError("http_429", retryable=True)
            if status >= 500:
                return ProviderExecutionError("http_5xx", retryable=True)
            if 400 <= status < 500:
                return ProviderExecutionError("http_4xx", retryable=False)
        if isinstance(exc, httpx.TransportError):
            return ProviderExecutionError("network", retryable=True)
    except ImportError:
        pass
    if isinstance(exc, (ConnectionError, OSError)):
        return ProviderExecutionError("network", retryable=True)
    if isinstance(
        exc,
        (json.JSONDecodeError, KeyError, IndexError, AttributeError, TypeError, ValueError),
    ):
        return ProviderMalformedResponseError()
    return ProviderExecutionError("provider_error", retryable=False)


def _usage_from_result(result: dict[str, Any]) -> dict[str, int]:
    usage = result.get("usage") or {}
    input_tokens = _nonnegative_int(
        usage.get("input_tokens", usage.get("prompt_tokens", 0))
    )
    output_tokens = _nonnegative_int(
        usage.get("output_tokens", usage.get("completion_tokens", 0))
    )
    return {"input_tokens": input_tokens, "output_tokens": output_tokens}


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ProviderMalformedResponseError()
    try:
        number = float(value or 0)
    except (TypeError, ValueError) as exc:
        raise ProviderMalformedResponseError() from exc
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ProviderMalformedResponseError()
    return int(number)


def _cost_from_usage(
    usage: dict[str, int], config: ProviderReliabilityConfig
) -> float:
    # Providers may report an authoritative cost; otherwise use configured rates.
    # The wrapper never guesses a price from prompt or response content.
    return round(
        (usage["input_tokens"] / 1000) * config.input_cost_per_1k_usd
        + (usage["output_tokens"] / 1000) * config.output_cost_per_1k_usd,
        8,
    )


def _cost_from_result(
    result: dict[str, Any],
    usage: dict[str, int],
    config: ProviderReliabilityConfig,
) -> float:
    """Use provider-reported cost when present, otherwise configured rates."""

    raw_cost = result.get("cost_usd")
    if raw_cost is None and isinstance(result.get("usage"), dict):
        raw_cost = result["usage"].get("cost_usd")
    if raw_cost is None:
        return _cost_from_usage(usage, config)
    if isinstance(raw_cost, bool):
        raise ProviderMalformedResponseError()
    try:
        cost = float(raw_cost)
    except (TypeError, ValueError) as exc:
        raise ProviderMalformedResponseError() from exc
    if not math.isfinite(cost) or cost < 0:
        raise ProviderMalformedResponseError()
    return round(cost, 8)


def _safe_label(value: str, fallback: str) -> str:
    import re

    text = str(value or "").strip()
    if not text or len(text) > 64 or not re.fullmatch(r"[A-Za-z0-9_.:/-]+", text):
        return fallback
    return text


def _record_provider_result(
    provider: str,
    model: str,
    *,
    outcome: str,
    elapsed_seconds: float,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    from services.observability import record_provider_result

    record_provider_result(
        provider=provider,
        model=model,
        outcome=outcome,
        elapsed_seconds=elapsed_seconds,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )


def _record_provider_error(provider: str, error_class: str) -> None:
    from services.observability import record_provider_error

    record_provider_error(provider=provider, error_class=error_class)


def _record_provider_timeout(provider: str) -> None:
    from services.observability import record_provider_timeout

    record_provider_timeout(provider=provider)


def _record_circuit(provider: str, model: str, state: str) -> None:
    from services.observability import record_circuit_breaker_state

    record_circuit_breaker_state(provider=provider, model=model, state=state)


__all__ = [
    "ProviderBulkheadError",
    "ProviderBudgetError",
    "ProviderCircuitOpenError",
    "ProviderExecutionError",
    "ProviderMalformedResponseError",
    "ProviderRateLimitError",
    "ProviderReliabilityConfig",
    "ReliableProvider",
    "provider_error_class",
    "reset_reliability_metrics",
    "wrap_provider",
]
