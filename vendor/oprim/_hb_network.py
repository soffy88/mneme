"""H-B E组: 网络 IO 扩展 (5)
validate_api_key / upload_share / revoke_share / fetch_models_dev / load_skill_raw
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from ._exceptions import HttpOprimError


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

ShareUrl = str


@dataclass
class ModelSpec:
    id: str
    name: str
    provider: str
    context_length: int = 0
    input_price: float = 0.0
    output_price: float = 0.0
    supports_tools: bool = False
    supports_vision: bool = False


# ---------------------------------------------------------------------------
# validate_api_key
# ---------------------------------------------------------------------------

_PROVIDER_ENDPOINTS: dict[str, tuple[str, str]] = {
    "anthropic": ("https://api.anthropic.com/v1/models", "x-api-key"),
    "openai": ("https://api.openai.com/v1/models", "Authorization"),
    "openrouter": ("https://openrouter.ai/api/v1/models", "Authorization"),
    "google": ("https://generativelanguage.googleapis.com/v1/models", "x-goog-api-key"),
    "mistral": ("https://api.mistral.ai/v1/models", "Authorization"),
    "cohere": ("https://api.cohere.ai/v1/models", "Authorization"),
}


async def validate_api_key(key: str, *, provider: str, timeout: float = 15) -> bool:
    """校验 API key 有效性（单次轻量 IO）。

    Args:
        key: API key 字符串。
        provider: provider 名称（anthropic/openai/openrouter/google/mistral/cohere）。
        timeout: 请求超时秒数，默认 15。

    Returns:
        True 表示 key 有效；False 表示 401/403 无效。

    Raises:
        ValueError: key 为空或 provider 未知。
        HttpOprimError: 网络错误（区分"无效"与"无法验证"）。
        TimeoutError: 超时。

    Example:
        >>> valid = await validate_api_key("sk-...", provider="anthropic")
    """
    if not key:
        raise ValueError("key must not be empty")
    provider = provider.lower()
    if provider not in _PROVIDER_ENDPOINTS:
        raise ValueError(
            f"unknown provider {provider!r}; supported: {sorted(_PROVIDER_ENDPOINTS)}"
        )

    url, header_name = _PROVIDER_ENDPOINTS[provider]

    if header_name == "Authorization":
        headers = {"Authorization": f"Bearer {key}"}
    elif header_name == "x-api-key":
        headers = {"x-api-key": key}
    elif header_name == "x-goog-api-key":
        headers = {"x-goog-api-key": key}
    else:
        headers = {header_name: key}  # pragma: no cover

    try:
        import httpx
    except ImportError as e:  # pragma: no cover
        raise HttpOprimError("httpx not installed", cause=e)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
    except httpx.TimeoutException as e:
        raise TimeoutError(f"validate_api_key timed out after {timeout}s") from e
    except httpx.RequestError as e:
        raise HttpOprimError(f"network error validating key: {e}", cause=e)

    if resp.status_code in (401, 403):
        return False
    return True


# ---------------------------------------------------------------------------
# upload_share
# ---------------------------------------------------------------------------

async def upload_share(
    payload: dict,
    *,
    endpoint: str,
    timeout: float = 60,
) -> ShareUrl:
    """上传 session payload，返回分享 URL。

    Args:
        payload: 要上传的 JSON-able dict。
        endpoint: POST 目标 URL。
        timeout: 请求超时秒数，默认 60。

    Returns:
        分享 URL 字符串。

    Raises:
        ValueError: endpoint 为空或非法。
        HttpOprimError: 上传失败。
        TimeoutError: 超时。

    Example:
        >>> url = await upload_share({"session": "..."}, endpoint="https://share.example.com/upload")
    """
    if not endpoint:
        raise ValueError("endpoint must not be empty")
    if not (endpoint.startswith("http://") or endpoint.startswith("https://")):
        raise ValueError(f"endpoint must start with http:// or https://: {endpoint!r}")

    try:
        import httpx
    except ImportError as e:  # pragma: no cover
        raise HttpOprimError("httpx not installed", cause=e)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(endpoint, json=payload)
    except httpx.TimeoutException as e:
        raise TimeoutError(f"upload_share timed out after {timeout}s") from e
    except httpx.RequestError as e:
        raise HttpOprimError(f"upload_share request failed: {e}", cause=e)

    if resp.status_code == 413:
        raise HttpOprimError(f"upload_share: payload too large (413) for {endpoint}")
    if not resp.is_success:
        raise HttpOprimError(
            f"upload_share failed {resp.status_code} for {endpoint}: {resp.text[:200]}"
        )

    data = resp.json()
    url = data.get("url") or data.get("share_url") or data.get("link") or ""
    if not url:
        raise HttpOprimError(f"upload_share: no URL in response: {data}")
    return str(url)


# ---------------------------------------------------------------------------
# revoke_share
# ---------------------------------------------------------------------------

async def revoke_share(url: ShareUrl, *, timeout: float = 30) -> None:
    """撤销分享链接（幂等）。

    Args:
        url: 分享 URL（由 upload_share 返回）。
        timeout: 请求超时秒数，默认 30。

    Raises:
        HttpOprimError: 网络错误（404/already-revoked 幂等不报错）。
        TimeoutError: 超时。

    Example:
        >>> await revoke_share("https://share.example.com/s/abc123")
    """
    try:
        import httpx
    except ImportError as e:  # pragma: no cover
        raise HttpOprimError("httpx not installed", cause=e)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.delete(url)
    except httpx.TimeoutException as e:
        raise TimeoutError(f"revoke_share timed out after {timeout}s") from e
    except httpx.RequestError as e:
        raise HttpOprimError(f"revoke_share request failed: {e}", cause=e)

    # 404 = already gone; treat as idempotent success
    if resp.status_code in (200, 204, 404):
        return
    if resp.status_code == 409:
        return  # already revoked
    raise HttpOprimError(
        f"revoke_share failed {resp.status_code} for {url}: {resp.text[:200]}"
    )


# ---------------------------------------------------------------------------
# fetch_models_dev
# ---------------------------------------------------------------------------

_MODELS_DEV_URL = "https://models.dev/api/models.json"


async def fetch_models_dev(
    *,
    refresh: bool = False,
    timeout: float = 30,
) -> list[ModelSpec]:
    """从 Models.dev 同步模型清单（75+ provider）。

    Args:
        refresh: True 时强制刷新（忽略调用方缓存提示）；本 oprim 不管理缓存。
        timeout: 请求超时秒数，默认 30。

    Returns:
        ModelSpec 列表。空响应返回 []。

    Raises:
        HttpOprimError: 网络失败或解析失败。
        TimeoutError: 超时。

    Example:
        >>> models = await fetch_models_dev()
        >>> len(models) > 0
        True
    """
    _ = refresh  # caching managed by caller / obase.cache

    try:
        import httpx
    except ImportError as e:  # pragma: no cover
        raise HttpOprimError("httpx not installed", cause=e)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(_MODELS_DEV_URL)
    except httpx.TimeoutException as e:
        raise TimeoutError(f"fetch_models_dev timed out after {timeout}s") from e
    except httpx.RequestError as e:
        raise HttpOprimError(f"fetch_models_dev network error: {e}", cause=e)

    if not resp.is_success:
        raise HttpOprimError(
            f"fetch_models_dev failed {resp.status_code}: {resp.text[:200]}"
        )

    try:
        raw = resp.json()
    except Exception as e:
        raise HttpOprimError(f"fetch_models_dev parse error: {e}", cause=e)

    if not raw:
        return []

    # models.dev format: dict keyed by provider, each with list of models
    specs: list[ModelSpec] = []
    if isinstance(raw, dict):
        for provider, entries in raw.items():
            if not isinstance(entries, (list, dict)):
                continue
            items = entries if isinstance(entries, list) else entries.get("models", [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                specs.append(ModelSpec(
                    id=item.get("id", ""),
                    name=item.get("name", item.get("id", "")),
                    provider=provider,
                    context_length=int(item.get("context_length", 0) or 0),
                    input_price=float(item.get("pricing", {}).get("input", 0) or 0),
                    output_price=float(item.get("pricing", {}).get("output", 0) or 0),
                    supports_tools=bool(item.get("supports_tool_use", False)),
                    supports_vision=bool(item.get("supports_vision", False)),
                ))
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            specs.append(ModelSpec(
                id=item.get("id", ""),
                name=item.get("name", item.get("id", "")),
                provider=item.get("provider", ""),
                context_length=int(item.get("context_length", 0) or 0),
                input_price=float(item.get("pricing", {}).get("input", 0) or 0),
                output_price=float(item.get("pricing", {}).get("output", 0) or 0),
            ))

    return specs


# ---------------------------------------------------------------------------
# load_skill_raw
# ---------------------------------------------------------------------------

async def load_skill_raw(path: Path) -> str:
    """读 SKILL.md 返回原始字符串（解析由 parse_skill_md H-A 处理）。

    Args:
        path: SKILL.md 文件路径。

    Returns:
        文件内容字符串；空文件返回 ""。

    Raises:
        FileNotFoundError: 文件不存在。

    Example:
        >>> raw = await load_skill_raw(Path("/skills/web_search/SKILL.md"))
        >>> raw.startswith("# SKILL")
        True
    """
    p = Path(path)
    loop = asyncio.get_event_loop()

    def _read() -> str:
        return p.read_text(encoding="utf-8")

    try:
        return await loop.run_in_executor(None, _read)
    except FileNotFoundError:
        raise FileNotFoundError(f"skill file not found: {path}")
