"""Single HTTP POST request with JSON body."""

from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import BaseModel

from oprim._exceptions import OprimError


class HTTPResponse(BaseModel):
    status_code: int
    body: dict[str, Any] | str
    headers: dict[str, str]
    elapsed_ms: float


def http_post(
    *,
    url: str,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> HTTPResponse:
    """Single HTTP POST request with JSON body.

    Unlike http_post_webhook, this is a generic POST without webhook-specific
    headers or signature logic. Raises on network errors.

    Args:
        url: Target URL
        json_data: JSON request body (optional)
        headers: Additional request headers
        timeout: Request timeout in seconds

    Returns:
        HTTPResponse with status_code, body, headers, elapsed_ms

    Raises:
        OprimError: Network error, timeout, DNS failure

    Example:
        >>> result = http_post(url="https://api.example.com/data", json_data={"key": "val"})
        >>> result.status_code
        200
    """
    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.post(url, json=json_data, headers=headers)

        elapsed_ms = (time.monotonic() - started) * 1000

        try:
            body: dict[str, Any] | str = response.json()
        except Exception:
            body = response.text

        response_headers = dict(response.headers)

        return HTTPResponse(
            status_code=response.status_code,
            body=body,
            headers=response_headers,
            elapsed_ms=elapsed_ms,
        )

    except httpx.TimeoutException as e:
        raise OprimError("timeout") from e
    except httpx.ConnectError as e:
        raise OprimError(f"connect_failed: {e}") from e
    except Exception as e:
        raise OprimError(f"unexpected: {type(e).__name__}: {e}") from e
