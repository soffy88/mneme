"""oprim.okx_rest_call — Generic OKX REST API helper."""
from __future__ import annotations

from typing import Any

_OKX_BASE = "https://www.okx.com"


async def okx_rest_call(
    path: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    auth: dict[str, str] | None = None,
    base_url: str = _OKX_BASE,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Execute an OKX REST request and return the parsed JSON response.

    Args:
        path: API path, e.g. ``"/api/v5/market/candles"``.
        method: HTTP verb (GET, POST, …).
        params: URL query parameters.
        body: JSON request body for POST requests.
        auth: Dict with ``api_key``, ``secret_key``, ``passphrase`` for
            authenticated endpoints.
        base_url: Override the OKX base URL (useful for sandbox).
        timeout: Request timeout in seconds.

    Returns:
        Parsed JSON dict — the full OKX envelope including ``code`` and
        ``data`` fields.

    Raises:
        OkxRestError: Non-200 HTTP status or OKX error code != "0".
    """
    import httpx  # noqa: PLC0415

    url = base_url.rstrip("/") + path
    headers: dict[str, str] = {"Content-Type": "application/json"}

    if auth:
        import base64  # noqa: PLC0415
        import hashlib  # noqa: PLC0415
        import hmac as _hmac  # noqa: PLC0415
        from datetime import datetime, timezone  # noqa: PLC0415

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        body_str = "" if body is None else __import__("json").dumps(body)
        prehash = ts + method.upper() + path + (body_str or "")
        sig = base64.b64encode(
            _hmac.new(
                auth["secret_key"].encode(),
                prehash.encode(),
                hashlib.sha256,
            ).digest()
        ).decode()
        headers.update({
            "OK-ACCESS-KEY": auth["api_key"],
            "OK-ACCESS-SIGN": sig,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": auth["passphrase"],
        })

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(
            method.upper(),
            url,
            params=params,
            json=body,
            headers=headers,
        )

    if resp.status_code != 200:
        raise OkxRestError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    if str(data.get("code", "0")) != "0":
        raise OkxRestError(f"OKX error {data.get('code')}: {data.get('msg', '')}")

    return data


class OkxRestError(Exception):
    """OKX REST API returned an error."""
