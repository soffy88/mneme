"""Network probe oprim — 4 atomic network connectivity operations."""

from __future__ import annotations

import socket
import time
from typing import Literal

import httpx
from pydantic import BaseModel

try:
    import dns.exception
    import dns.resolver
except ImportError:
    dns = None  # type: ignore[assignment]

from oprim._exceptions import (
    OprimConnectionError,
    OprimTimeoutError,
    OprimValidationError,
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PortCheckResult(BaseModel):
    host: str
    port: int
    reachable: bool
    elapsed_ms: int
    error: str | None


class HealthProbeResult(BaseModel):
    url: str
    status_code: int | None
    healthy: bool
    elapsed_ms: int
    response_body_preview: str | None
    error: str | None


class DNSResolveResult(BaseModel):
    hostname: str
    record_type: str
    records: list[str]
    ttl: int | None
    elapsed_ms: int
    error: str | None


class HttpResponse(BaseModel):
    status_code: int
    headers: dict[str, str]
    body: bytes
    elapsed_ms: int


# ---------------------------------------------------------------------------
# 6.1 tcp_port_check
# ---------------------------------------------------------------------------


def tcp_port_check(
    *,
    host: str,
    port: int,
    timeout_sec: int = 5,
) -> PortCheckResult:
    """TCP 端口连通性探测 (建立 connection 即关闭).

    永不 raise 网络错误 (返 reachable=False), 只 raise 输入错误.

    Args:
        host: 目标主机名或 IP
        port: 目标端口
        timeout_sec: 连接超时秒数

    Returns:
        PortCheckResult

    Raises:
        OprimValidationError: port 不在 1-65535
    """
    if not 1 <= port <= 65535:
        raise OprimValidationError(f"Port must be between 1 and 65535, got {port}")

    t0 = time.monotonic()
    error: str | None = None
    reachable = False

    try:
        sock = socket.create_connection((host, port), timeout=timeout_sec)
        sock.close()
        reachable = True
    except TimeoutError:
        error = "timeout"
    except ConnectionRefusedError:
        error = "connection refused"
    except socket.gaierror as exc:
        error = f"dns failure: {exc}"
    except OSError as exc:
        error = str(exc)

    elapsed = int((time.monotonic() - t0) * 1000)
    return PortCheckResult(
        host=host,
        port=port,
        reachable=reachable,
        elapsed_ms=elapsed,
        error=error,
    )


# ---------------------------------------------------------------------------
# 6.2 http_health_probe
# ---------------------------------------------------------------------------


def http_health_probe(
    *,
    url: str,
    timeout_sec: int = 5,
    expected_status: int = 200,
    method: Literal["GET", "HEAD"] = "GET",
    follow_redirects: bool = False,
) -> HealthProbeResult:
    """HTTP 健康探测.

    永不 raise 网络错误.

    Args:
        url: 目标 URL
        timeout_sec: 请求超时
        expected_status: 期望 HTTP status code
        method: HTTP 方法 ("GET" 或 "HEAD")
        follow_redirects: 是否跟随重定向

    Returns:
        HealthProbeResult
    """
    t0 = time.monotonic()
    status_code: int | None = None
    body_preview: str | None = None
    error: str | None = None

    try:
        with httpx.Client(timeout=timeout_sec, follow_redirects=follow_redirects) as client:
            resp = client.request(method, url)
        status_code = resp.status_code
        if method == "GET":
            body_preview = resp.text[:200]
    except httpx.ConnectError as exc:
        error = f"connection error: {exc}"
    except httpx.TimeoutException:
        error = "timeout"
    except httpx.HTTPError as exc:
        error = str(exc)

    elapsed = int((time.monotonic() - t0) * 1000)
    healthy = status_code == expected_status

    return HealthProbeResult(
        url=url,
        status_code=status_code,
        healthy=healthy,
        elapsed_ms=elapsed,
        response_body_preview=body_preview,
        error=error,
    )


# ---------------------------------------------------------------------------
# 6.3 dns_resolve
# ---------------------------------------------------------------------------


def dns_resolve(
    *,
    hostname: str,
    record_type: Literal["A", "AAAA", "CNAME", "MX", "TXT"] = "A",
    nameserver: str | None = None,
    timeout_sec: int = 5,
) -> DNSResolveResult:
    """DNS 解析.

    永不 raise 解析错误 (返 records=[] + error="...").

    Args:
        hostname: 要解析的主机名
        record_type: DNS 记录类型
        nameserver: 使用指定 DNS server (可选)
        timeout_sec: 解析超时

    Returns:
        DNSResolveResult
    """
    if dns is None:
        return DNSResolveResult(
            hostname=hostname,
            record_type=record_type,
            records=[],
            ttl=None,
            elapsed_ms=0,
            error="dnspython not installed",
        )

    t0 = time.monotonic()
    records: list[str] = []
    ttl: int | None = None
    error: str | None = None

    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = float(timeout_sec)
        if nameserver:
            resolver.nameservers = [nameserver]

        answers = resolver.resolve(hostname, record_type)
        ttl = int(answers.rrset.ttl) if answers.rrset else None

        for rdata in answers:
            txt = rdata.to_text()
            records.append(txt.strip('"'))
    except dns.resolver.NXDOMAIN:
        error = f"NXDOMAIN: {hostname} does not exist"
    except dns.resolver.NoAnswer:
        error = f"No {record_type} records for {hostname}"
    except dns.resolver.Timeout:
        error = "DNS query timed out"
    except dns.exception.DNSException as exc:
        error = str(exc)
    except Exception as exc:
        error = str(exc)

    elapsed = int((time.monotonic() - t0) * 1000)
    return DNSResolveResult(
        hostname=hostname,
        record_type=record_type,
        records=records,
        ttl=ttl,
        elapsed_ms=elapsed,
        error=error,
    )


# ---------------------------------------------------------------------------
# 6.4 http_request_once
# ---------------------------------------------------------------------------


def http_request_once(
    *,
    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"],
    url: str,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout_sec: int = 10,
    verify_tls: bool = True,
) -> HttpResponse:
    """通用 HTTP 单次调用 (不重试, 不限流).

    Args:
        method: HTTP 方法
        url: 目标 URL
        headers: 请求头
        body: 请求体 (bytes)
        timeout_sec: 请求超时
        verify_tls: 是否验证 TLS 证书

    Returns:
        HttpResponse

    Raises:
        OprimConnectionError: DNS / TCP 失败 / TLS 失败
        OprimTimeoutError: 请求超时
    """
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=timeout_sec, verify=verify_tls) as client:
            resp = client.request(
                method,
                url,
                headers=headers or {},
                content=body,
            )
    except httpx.TimeoutException as exc:
        raise OprimTimeoutError(f"HTTP request timed out: {exc}") from exc
    except httpx.ConnectError as exc:
        raise OprimConnectionError(f"HTTP connection failed: {exc}") from exc
    except httpx.HTTPError as exc:
        raise OprimConnectionError(f"HTTP error: {exc}") from exc

    elapsed = int((time.monotonic() - t0) * 1000)
    return HttpResponse(
        status_code=resp.status_code,
        headers=dict(resp.headers),
        body=resp.content,
        elapsed_ms=elapsed,
    )


# ---------------------------------------------------------------------------
# Aegis IMPL SPEC v1.0 — short-name aliases (B2)
# ---------------------------------------------------------------------------

network_port_check = tcp_port_check
network_http_health = http_health_probe
network_dns_resolve = dns_resolve
