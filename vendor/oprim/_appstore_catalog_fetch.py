"""AppStore catalog fetch oprim — fetch app metadata from a catalog endpoint."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel

from oprim._exceptions import (
    OprimConnectionError,
    OprimNotFoundError,
    OprimTimeoutError,
)


class AppCatalogEntry(BaseModel):
    app_id: str
    name: str
    version: str
    image: str
    compose_file: str
    routes: list[dict[str, Any]]
    env_vars: dict[str, str]
    service_url: str
    description: str
    tags: list[str]


def appstore_catalog_fetch(
    *,
    catalog_url: str,
    app_id: str,
    timeout_sec: int = 10,
    auth_token: str | None = None,
) -> AppCatalogEntry:
    """从 AppStore catalog API 拉取单个 App 元数据.

    Args:
        catalog_url: catalog API base URL (e.g. "http://appstore.internal/api/v1")
        app_id: App 唯一标识
        timeout_sec: 请求超时
        auth_token: Bearer token (可选)

    Returns:
        AppCatalogEntry

    Raises:
        OprimNotFoundError: app_id 不存在 (HTTP 404)
        OprimConnectionError: 网络错误或 5xx
        OprimTimeoutError: 请求超时
    """
    url = catalog_url.rstrip("/") + f"/apps/{app_id}"
    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    try:
        resp = httpx.get(url, headers=headers, timeout=timeout_sec)
    except httpx.TimeoutException as exc:
        raise OprimTimeoutError(f"Catalog request timed out: {exc}") from exc
    except httpx.ConnectError as exc:
        raise OprimConnectionError(f"Cannot reach catalog at {catalog_url}: {exc}") from exc
    except httpx.HTTPError as exc:
        raise OprimConnectionError(f"Catalog HTTP error: {exc}") from exc

    if resp.status_code == 404:
        raise OprimNotFoundError(f"App '{app_id}' not found in catalog at {catalog_url}")
    if not resp.is_success:
        raise OprimConnectionError(
            f"Catalog API returned HTTP {resp.status_code}: {resp.text[:200]}"
        )

    data = resp.json()
    return AppCatalogEntry(
        app_id=data.get("app_id", app_id),
        name=data.get("name", app_id),
        version=data.get("version", "latest"),
        image=data.get("image", ""),
        compose_file=data.get("compose_file", ""),
        routes=data.get("routes", []),
        env_vars=data.get("env_vars", {}),
        service_url=data.get("service_url", ""),
        description=data.get("description", ""),
        tags=data.get("tags", []),
    )
