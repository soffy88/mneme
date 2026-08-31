# Mneme v0.1.0-rc5 provider qualification

Status: **code/reliability gate PASS; live-provider gate OWNER_BLOCKED**.

## Unified execution contract

All existing registry LLM/VLM providers (Veya, Qwen, Ollama, and the default
registry providers) are installed through `services.providers.reliability`.
The chat tool-calling adapter uses the same wrapper. The wrapper is the only
place that applies provider timeout, retry, circuit, bulkhead, rate, budget,
and provider metrics policy.

## Policy verified

- Connect timeout: default 5 s, hard maximum 15 s.
- Read/write timeout: default 60 s, hard maximum 120 s.
- Logical request deadline: default 90 s, hard maximum 120 s, including retry
  backoff.
- Retry is opt-in and only enabled for side-effect-free provider completion
  calls. Maximum 2 retries. Retryable classes are network/timeout, HTTP 429,
  and HTTP 5xx. HTTP 4xx and malformed responses are not retried.
- Backoff is bounded exponential (`0.25 s * 2^n`, capped at 2 s) plus bounded
  jitter (default 0.25 s).
- Circuit breaker opens after 3 consecutive provider failures and permits one
  half-open probe after 30 s. Staging used the same policy with a 2 s recovery
  window for qualification speed.
- Default bulkhead is 8 concurrent calls with a bounded 50 ms acquisition
  wait. Staging used size 2 and 10 ms wait.
- Default rate limit is 60 provider attempts/minute. Request, input-token,
  output-token, and USD cost windows are bounded and fail closed.

## Reliability matrix

`tests/test_provider_reliability.py`: **17 passed**. The matrix covers success,
connect/read timeout bounds, retryable 5xx, 429, non-retryable 4xx, malformed
responses, circuit open/half-open/recovery, bulkhead saturation, rate limiting,
request/token/cost budgets, retry idempotency, no duplicate Evidence/FSRS,
provider failure non-advancement, and low-cardinality metric label checks.

The exact RC5 staging API image also ran a deterministic fake OpenAI-compatible
endpoint. Synthetic probes produced: success with input/output usage,
`read_timeout`, `http_5xx`, `http_429`, and `malformed_response`. A single
process drove three 5xx failures, observed circuit failure, waited for the
half-open window, and recovered successfully. The captured metric snapshot
contained provider/model/outcome, error class, token, cost, and circuit-state
records only; no prompt, response, user ID, email, phone, or secret was
printed or used as a label.

Malformed provider data raises a typed safe failure. It cannot create learning
Evidence or advance mastery/FSRS; the regression tests cover both duplicate
retry protection and failure non-advancement. Deterministic/core learning
paths remain available when the provider is unavailable.

## Observability contract

The health metrics endpoint exposes the requested low-cardinality series:

`provider_requests_total{provider,model,outcome}`  
`provider_errors_total{provider,error_class}`  
`provider_timeouts_total{provider}`  
`provider_latency_seconds{provider,model}`  
`provider_input_tokens_total{provider,model}`  
`provider_output_tokens_total{provider,model}`  
`provider_cost_total{provider,model}`  
`circuit_breaker_state{provider,model,state}`

Labels are bounded provider/model/outcome/error/state values. No user,
contact, prompt, content, or secret value is retained by the metrics contract.

## Secret and live-provider gate

The exact artifact build contexts came from `git archive`; `.env` files and
runtime credentials are excluded by Docker ignore rules. Provider status only
reports key presence/type/model metadata. Redacted gitleaks delta is clean;
the historical baseline contains only existing false-positive generic-key
matches in old generated artifacts and fixtures. No new credential was found.

Owner did not provide a new staging secret for the requested live text call or
synthetic VLM call in this run. Therefore live text connectivity is
**OWNER_BLOCKED**, live VLM connectivity is **OWNER_BLOCKED**, and live token /
cost proof is **NOT_RUN**. No real provider endpoint was called.
