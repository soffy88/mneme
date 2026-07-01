"""Auto-split from hicode whl."""

from __future__ import annotations
from ._exceptions import HttpOprimError
from .llm._types import HttpResponse

async def http_fetch(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | bytes | dict | None = None,
    timeout: float = 30.0,
    follow_redirects: bool = True,
    raise_on_error: bool = False,
) -> HttpResponse:
    """单次 HTTP 请求（async 本性：网络 IO 等待）。

    Args:
        url: 请求 URL（含 schema）。
        method: HTTP 方法，默认 GET。
        headers: 额外请求头。
        body: 请求体；dict 时自动序列化为 JSON 并设 Content-Type。
        timeout: 超时秒数，默认 30。
        follow_redirects: 是否跟随重定向，默认 True。
        raise_on_error: True 时 4xx/5xx 抛 HttpOprimError，默认 False。

    Returns:
        HttpResponse(status_code, text, headers, url)。

    Raises:
        HttpOprimError: 网络错误、超时、或 raise_on_error=True 时的 4xx/5xx。

    Example:
        >>> resp = await http_fetch("https://httpbin.org/get")
        >>> resp.ok
        True
        >>> resp.status_code
        200
    """
    try:
        import httpx
    except ImportError as e:  # pragma: no cover
        raise HttpOprimError("httpx not installed: pip install httpx", cause=e)

    req_headers = dict(headers or {})
    req_content: bytes | None = None
    req_json: dict | None = None

    if body is not None:
        if isinstance(body, dict):
            req_json = body
        elif isinstance(body, str):  # pragma: no cover
            req_content = body.encode()  # pragma: no cover
        else:  # pragma: no cover
            req_content = body  # pragma: no cover

    try:
        async with httpx.AsyncClient(
            follow_redirects=follow_redirects,
            timeout=timeout,
        ) as client:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=req_headers,
                content=req_content,
                json=req_json,
            )
    except httpx.TimeoutException as e:
        raise HttpOprimError(f"request timed out after {timeout}s: {url}", cause=e)
    except httpx.RequestError as e:
        raise HttpOprimError(f"request failed: {url}", cause=e)

    result = HttpResponse(
        status_code=response.status_code,
        text=response.text,
        headers=dict(response.headers),
        url=str(response.url),
    )

    if raise_on_error and not result.ok:
        raise HttpOprimError(
            f"HTTP {result.status_code} for {url}: {result.text[:200]}"
        )

    return result
