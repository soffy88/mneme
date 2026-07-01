"""Caddy oprim — 3 atomic Caddy Admin API operations."""

from __future__ import annotations

import time
from datetime import UTC
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from oprim._exceptions import (
    OprimConnectionError,
    OprimValidationError,
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ReloadResult(BaseModel):
    success: bool
    elapsed_ms: int
    config_id: str | None


class Route(BaseModel):
    id: str | None
    matchers: list[dict[str, Any]]
    handlers: list[dict[str, Any]]
    target_upstream: str | None


class CertStatus(BaseModel):
    domain: str
    issued: bool
    issuer: str | None
    not_before: str | None
    not_after: str | None
    days_until_expiry: int | None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _admin_request(
    method: str,
    admin_url: str,
    path: str,
    json_body: dict[str, Any] | None = None,
    timeout_sec: int = 10,
) -> httpx.Response:
    url = admin_url.rstrip("/") + "/" + path.lstrip("/")
    try:
        if method == "GET":
            resp = httpx.get(url, timeout=timeout_sec)
        elif method == "POST":
            resp = httpx.post(url, json=json_body, timeout=timeout_sec)
        else:
            resp = httpx.request(method, url, json=json_body, timeout=timeout_sec)
    except httpx.ConnectError as exc:
        raise OprimConnectionError(f"Cannot reach Caddy admin API at {admin_url}: {exc}") from exc
    except httpx.TimeoutException as exc:
        raise OprimConnectionError(f"Caddy admin API request timed out: {exc}") from exc
    return resp


def _extract_upstream(handlers: list[dict[str, Any]]) -> str | None:
    """Extract first reverse_proxy upstream from handler list."""
    for handler in handlers:
        if handler.get("handler") == "reverse_proxy":
            upstreams = handler.get("upstreams", [])
            if upstreams:
                return (
                    str(upstreams[0].get("dial")) if upstreams[0].get("dial") is not None else None
                )
    return None


# ---------------------------------------------------------------------------
# 5.2 caddy_admin_reload
# ---------------------------------------------------------------------------


def caddy_admin_reload(
    *,
    admin_url: str,
    new_config: dict[str, Any],
    timeout_sec: int = 10,
) -> ReloadResult:
    """加载新的 Caddy 配置 (整体替换, atomic).

    Args:
        admin_url: Caddy admin API URL (e.g. "http://localhost:2019")
        new_config: 完整 Caddy JSON config
        timeout_sec: 请求超时

    Returns:
        ReloadResult

    Raises:
        OprimValidationError: config 格式无效 (Caddy 返 400)
        OprimConnectionError
    """
    t0 = time.monotonic()
    resp = _admin_request("POST", admin_url, "/load", json_body=new_config, timeout_sec=timeout_sec)
    elapsed = int((time.monotonic() - t0) * 1000)

    if resp.status_code == 400 or resp.status_code == 422:
        raise OprimValidationError(
            f"Invalid Caddy config (HTTP {resp.status_code}): {resp.text[:200]}"
        )
    if not resp.is_success:
        raise OprimConnectionError(f"Caddy /load returned {resp.status_code}: {resp.text[:200]}")

    config_id = resp.headers.get("Etag") or resp.headers.get("X-Config-Id")

    return ReloadResult(
        success=True,
        elapsed_ms=elapsed,
        config_id=config_id,
    )


# ---------------------------------------------------------------------------
# 5.3 caddy_routes_list
# ---------------------------------------------------------------------------


def caddy_routes_list(
    *,
    admin_url: str,
    server_name: str = "srv0",
    timeout_sec: int = 5,
) -> list[Route]:
    """列出当前 Caddy 所有路由 (从 config tree 提取).

    Args:
        admin_url: Caddy admin API URL
        server_name: Caddy server block name (default "srv0")
        timeout_sec: 请求超时

    Returns:
        Route 列表

    Raises:
        OprimConnectionError
    """
    path = f"/config/apps/http/servers/{server_name}/routes"
    resp = _admin_request("GET", admin_url, path, timeout_sec=timeout_sec)

    if resp.status_code == 404:
        return []
    if not resp.is_success:
        raise OprimConnectionError(
            f"Caddy config API returned {resp.status_code}: {resp.text[:200]}"
        )

    raw_routes = resp.json()
    if not isinstance(raw_routes, list):
        return []

    result = []
    for r in raw_routes:
        handlers = r.get("handle", [])
        result.append(
            Route(
                id=r.get("@id"),
                matchers=r.get("match", []),
                handlers=handlers,
                target_upstream=_extract_upstream(handlers),
            )
        )
    return result


# ---------------------------------------------------------------------------
# 5.4 caddy_certificates_status
# ---------------------------------------------------------------------------


def caddy_certificates_status(
    *,
    admin_url: str,
    domain: str,
    timeout_sec: int = 5,
) -> CertStatus:
    """查 Caddy 为指定域名管理的证书状态.

    Note:
        Caddy does not expose a direct per-domain certificate query endpoint.
        This implementation queries /pki/ca/local and the certificates list
        endpoint. If Caddy does not manage TLS for the domain, returns
        issued=False with null fields.

    Args:
        admin_url: Caddy admin API URL
        domain: 域名
        timeout_sec: 请求超时

    Returns:
        CertStatus

    Raises:
        OprimConnectionError
    """
    from datetime import datetime

    resp = _admin_request("GET", admin_url, "/certificates", timeout_sec=timeout_sec)

    if resp.status_code == 404:
        # Caddy version without /certificates endpoint
        return CertStatus(
            domain=domain,
            issued=False,
            issuer=None,
            not_before=None,
            not_after=None,
            days_until_expiry=None,
        )
    if not resp.is_success:
        raise OprimConnectionError(f"Caddy /certificates returned {resp.status_code}")

    certs = resp.json()
    if not isinstance(certs, list):
        certs = []

    # Find certificate matching domain
    for cert in certs:
        names = cert.get("names", [])
        if domain in names or f"*.{'.'.join(domain.split('.')[1:])}" in names:
            not_after_raw = cert.get("not_after") or cert.get("expiry")
            not_before_raw = cert.get("not_before") or cert.get("issued")
            days_left = None
            if not_after_raw:
                try:
                    exp = datetime.fromisoformat(not_after_raw.replace("Z", "+00:00"))
                    delta = exp - datetime.now(UTC)
                    days_left = delta.days
                except (ValueError, TypeError):
                    pass
            return CertStatus(
                domain=domain,
                issued=True,
                issuer=cert.get("issuer"),
                not_before=not_before_raw,
                not_after=not_after_raw,
                days_until_expiry=days_left,
            )

    return CertStatus(
        domain=domain,
        issued=False,
        issuer=None,
        not_before=None,
        not_after=None,
        days_until_expiry=None,
    )


# ---------------------------------------------------------------------------
# 5.5 caddy_admin_post
# ---------------------------------------------------------------------------


def caddy_admin_post(
    *,
    admin_url: str,
    path: str,
    body: dict[str, Any] | None = None,
    method: Literal["POST", "PATCH", "PUT", "DELETE"] = "POST",
    timeout_sec: int = 10,
) -> dict[str, Any]:
    """向 Caddy Admin API 发送 POST/PATCH/PUT/DELETE 请求.

    Args:
        admin_url: Caddy admin API URL
        path: API 路径 (e.g. "/config/...")
        body: 请求体
        method: HTTP 方法
        timeout_sec: 超时

    Returns:
        JSON 响应体 (若有) 或 {"status": "ok"}

    Raises:
        OprimValidationError: 4xx 错误
        OprimConnectionError: 5xx 或 连接错误
    """
    from typing import cast

    resp = _admin_request(method, admin_url, path, json_body=body, timeout_sec=timeout_sec)

    if resp.status_code >= 400 and resp.status_code < 500:
        raise OprimValidationError(f"Caddy API error (HTTP {resp.status_code}): {resp.text[:500]}")
    if not resp.is_success:
        raise OprimConnectionError(f"Caddy API failed (HTTP {resp.status_code}): {resp.text[:500]}")

    try:
        return cast(dict[str, Any], resp.json())
    except Exception:
        return {"status": "ok", "http_code": resp.status_code}


# ---------------------------------------------------------------------------
# Aegis IMPL SPEC v1.0 — caddy_admin_config / caddy_admin_routes /
#                         caddy_route_add_atomic / caddy_route_remove_atomic
# ---------------------------------------------------------------------------

caddy_admin_routes = caddy_routes_list


def caddy_admin_config(
    *,
    admin_url: str,
    timeout_sec: int = 5,
) -> dict[str, Any]:
    """获取 Caddy 完整 JSON 配置.

    Args:
        admin_url: Caddy admin API URL (e.g. "http://localhost:2019")
        timeout_sec: 请求超时

    Returns:
        完整 Caddy JSON config dict

    Raises:
        OprimConnectionError
    """
    from typing import cast

    resp = _admin_request("GET", admin_url, "/config/", timeout_sec=timeout_sec)
    if not resp.is_success:
        raise OprimConnectionError(f"Caddy /config/ returned {resp.status_code}: {resp.text[:200]}")
    return cast(dict[str, Any], resp.json())


def caddy_route_add_atomic(
    *,
    admin_url: str,
    server_name: str = "srv0",
    route: dict[str, Any],
    position: int | None = None,
    timeout_sec: int = 10,
) -> dict[str, Any]:
    """原子添加单条路由到 Caddy (不影响其他路由).

    Strategy: GET 当前路由列表 → 插入新路由 → PUT 整体替换.
    全程无中间状态暴露给流量 (Caddy /config/ PUT 是 atomic).

    Args:
        admin_url: Caddy admin API URL
        server_name: Caddy server block name (default "srv0")
        route: 新路由 dict (Caddy JSON route 格式)
        position: 插入位置 (None = 追加到末尾)
        timeout_sec: 请求超时

    Returns:
        {"status": "ok", "routes_total": int}

    Raises:
        OprimConnectionError / OprimValidationError
    """
    from typing import cast

    path = f"/config/apps/http/servers/{server_name}/routes"

    # GET current routes
    get_resp = _admin_request("GET", admin_url, path, timeout_sec=timeout_sec)
    if not get_resp.is_success:
        raise OprimConnectionError(f"Failed to fetch routes: HTTP {get_resp.status_code}")
    routes: list[dict[str, Any]] = cast(list, get_resp.json()) or []

    # Insert
    if position is None:
        routes.append(route)
    else:
        routes.insert(position, route)

    # PUT atomically
    put_resp = _admin_request("PUT", admin_url, path, json_body=routes, timeout_sec=timeout_sec)
    if put_resp.status_code >= 400 and put_resp.status_code < 500:
        raise OprimValidationError(
            f"Caddy rejected route config (HTTP {put_resp.status_code}): {put_resp.text[:400]}"
        )
    if not put_resp.is_success:
        raise OprimConnectionError(
            f"Caddy PUT routes failed (HTTP {put_resp.status_code}): {put_resp.text[:200]}"
        )
    return {"status": "ok", "routes_total": len(routes)}


def caddy_route_remove_atomic(
    *,
    admin_url: str,
    server_name: str = "srv0",
    route_id: str,
    timeout_sec: int = 10,
) -> dict[str, Any]:
    """原子移除单条路由 (按 route id 匹配).

    Strategy: GET 当前路由列表 → 过滤掉目标 id → PUT 整体替换.

    Args:
        admin_url: Caddy admin API URL
        server_name: Caddy server block name (default "srv0")
        route_id: 要移除的路由 "@id" 字段值
        timeout_sec: 请求超时

    Returns:
        {"status": "ok", "removed": bool, "routes_total": int}

    Raises:
        OprimConnectionError / OprimValidationError
    """
    from typing import cast

    path = f"/config/apps/http/servers/{server_name}/routes"

    get_resp = _admin_request("GET", admin_url, path, timeout_sec=timeout_sec)
    if not get_resp.is_success:
        raise OprimConnectionError(f"Failed to fetch routes: HTTP {get_resp.status_code}")
    routes: list[dict[str, Any]] = cast(list, get_resp.json()) or []

    original_len = len(routes)
    filtered = [r for r in routes if r.get("@id") != route_id]
    removed = len(filtered) < original_len

    put_resp = _admin_request("PUT", admin_url, path, json_body=filtered, timeout_sec=timeout_sec)
    if put_resp.status_code >= 400 and put_resp.status_code < 500:
        raise OprimValidationError(
            f"Caddy rejected route update (HTTP {put_resp.status_code}): {put_resp.text[:400]}"
        )
    if not put_resp.is_success:
        raise OprimConnectionError(
            f"Caddy PUT routes failed (HTTP {put_resp.status_code}): {put_resp.text[:200]}"
        )
    return {"status": "ok", "removed": removed, "routes_total": len(filtered)}
