from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import BaseModel

MAX_RESPONSE_BODY_BYTES = 4096


class WebhookResult(BaseModel):
    success: bool
    status_code: int | None  # None = request never completed (network error)
    elapsed_ms: float
    response_body: str  # truncated to 4096 chars
    error: str | None  # "timeout" / "connect_failed:..." / "http_4xx" / "http_5xx" / ...


def http_post_webhook(
    *,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout_sec: float = 10.0,
    signature: str | None = None,
    signature_header: str = "X-Aegis-Signature",
    user_agent: str = "obase-webhook/1.0",
) -> WebhookResult:
    """Single HTTP POST webhook delivery.

    Never raises. All errors returned via WebhookResult.success=False.
    follow_redirects=False (SSRF prevention).
    response_body truncated to 4096 chars.
    """
    request_headers: dict[str, str] = {
        "Content-Type": "application/json",
        "User-Agent": user_agent,
    }
    if headers:
        request_headers.update(headers)
    if signature:
        request_headers[signature_header] = signature

    started = time.monotonic()
    try:
        try:
            payload_json = json.dumps(payload, default=str)
        except (TypeError, ValueError) as e:
            elapsed_ms = (time.monotonic() - started) * 1000
            return WebhookResult(
                success=False,
                status_code=None,
                elapsed_ms=elapsed_ms,
                response_body="",
                error=f"payload_not_serializable: {e}",
            )

        with httpx.Client(follow_redirects=False, timeout=timeout_sec) as client:
            response = client.post(url, content=payload_json, headers=request_headers)

        elapsed_ms = (time.monotonic() - started) * 1000
        body = response.text[:MAX_RESPONSE_BODY_BYTES]

        if response.is_success:
            return WebhookResult(
                success=True,
                status_code=response.status_code,
                elapsed_ms=elapsed_ms,
                response_body=body,
                error=None,
            )
        else:
            sc = response.status_code
            if 300 <= sc < 400:
                error_class = "http_3xx"
            elif 400 <= sc < 500:
                error_class = "http_4xx"
            else:
                error_class = "http_5xx"
            return WebhookResult(
                success=False,
                status_code=response.status_code,
                elapsed_ms=elapsed_ms,
                response_body=body,
                error=error_class,
            )

    except httpx.TimeoutException:
        elapsed_ms = (time.monotonic() - started) * 1000
        return WebhookResult(
            success=False,
            status_code=None,
            elapsed_ms=elapsed_ms,
            response_body="",
            error="timeout",
        )
    except httpx.ConnectError as e:
        elapsed_ms = (time.monotonic() - started) * 1000
        return WebhookResult(
            success=False,
            status_code=None,
            elapsed_ms=elapsed_ms,
            response_body="",
            error=f"connect_failed: {e}",
        )
    except Exception as e:
        elapsed_ms = (time.monotonic() - started) * 1000
        return WebhookResult(
            success=False,
            status_code=None,
            elapsed_ms=elapsed_ms,
            response_body="",
            error=f"unexpected: {type(e).__name__}: {e}",
        )
