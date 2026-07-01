"""Metrics and logs oprim — 4 atomic Prometheus / Loki / structlog operations."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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

class InstantResultSample(BaseModel):
    metric: dict[str, str]
    value: float
    timestamp: float


class InstantResult(BaseModel):
    result_type: Literal["vector", "scalar", "string"]
    samples: list[InstantResultSample]
    elapsed_ms: int


class RangeResultSeries(BaseModel):
    metric: dict[str, str]
    values: list[tuple[float, float]]


class RangeResult(BaseModel):
    series: list[RangeResultSeries]
    elapsed_ms: int


class LogEntry(BaseModel):
    timestamp: str
    labels: dict[str, str]
    message: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _prom_request(endpoint: str, path: str, params: dict[str, Any], timeout_sec: int) -> dict[str, Any]:
    url = endpoint.rstrip("/") + "/" + path.lstrip("/")
    try:
        resp = httpx.get(url, params=params, timeout=timeout_sec)
    except httpx.ConnectError as exc:
        raise OprimConnectionError(f"Cannot reach Prometheus at {endpoint}: {exc}") from exc
    except httpx.TimeoutException as exc:
        raise OprimConnectionError(f"Prometheus request timed out: {exc}") from exc

    if resp.status_code == 400:
        data = resp.json()
        raise OprimValidationError(f"PromQL error: {data.get('error', resp.text[:200])}")
    if not resp.is_success:
        raise OprimConnectionError(f"Prometheus returned {resp.status_code}: {resp.text[:200]}")

    return resp.json()  # type: ignore[no-any-return]


def _parse_iso_or_epoch(ts: str) -> str:
    """Return ts as-is if already epoch-like, otherwise assume ISO 8601."""
    try:
        float(ts)
        return ts  # already a unix epoch string
    except ValueError:
        # Parse ISO 8601 and convert to unix epoch string
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return str(dt.timestamp())


# ---------------------------------------------------------------------------
# 8.1 prometheus_instant_query
# ---------------------------------------------------------------------------

def prometheus_instant_query(
    *,
    endpoint: str,
    query: str,
    time: str | None = None,
    timeout_sec: int = 10,
) -> InstantResult:
    """Prometheus 即时查询.

    Args:
        endpoint: Prometheus URL (e.g. "http://localhost:9090")
        query: PromQL 表达式
        time: 查询时间 (不传则用 server 当前时间)
        timeout_sec: 请求超时

    Returns:
        InstantResult

    Raises:
        OprimValidationError: PromQL 语法错
        OprimConnectionError
    """
    params: dict[str, Any] = {"query": query}
    if time is not None:
        params["time"] = time

    t0 = _time()
    data = _prom_request(endpoint, "/api/v1/query", params, timeout_sec)
    elapsed = int((_time() - t0) * 1000)

    result_type = data.get("data", {}).get("resultType", "vector")
    raw_results = data.get("data", {}).get("result", [])

    samples: list[InstantResultSample] = []
    if result_type == "vector":
        for item in raw_results:
            ts, val = item["value"]
            try:
                float_val = float(val)
            except (ValueError, TypeError):
                float_val = 0.0
            samples.append(InstantResultSample(
                metric=item.get("metric", {}),
                value=float_val,
                timestamp=float(ts),
            ))
    elif result_type == "scalar":
        ts, val = raw_results
        samples.append(InstantResultSample(
            metric={},
            value=float(val),
            timestamp=float(ts),
        ))

    valid_types = {"vector", "scalar", "string"}
    rt = result_type if result_type in valid_types else "vector"

    return InstantResult(
        result_type=rt,  # type: ignore[arg-type]
        samples=samples,
        elapsed_ms=elapsed,
    )


def _time() -> float:
    import time as _time_mod
    return _time_mod.monotonic()


# ---------------------------------------------------------------------------
# 8.2 prometheus_range_query
# ---------------------------------------------------------------------------

def prometheus_range_query(
    *,
    endpoint: str,
    query: str,
    start: str,
    end: str,
    step: str,
    timeout_sec: int = 30,
) -> RangeResult:
    """Prometheus 范围查询.

    Args:
        endpoint: Prometheus URL
        query: PromQL 表达式
        start: 起始时间 (ISO 8601 或 unix epoch 字符串)
        end: 截止时间 (ISO 8601 或 unix epoch 字符串)
        step: 步长 (e.g. "15s", "1m")
        timeout_sec: 请求超时

    Returns:
        RangeResult

    Raises:
        OprimValidationError / OprimConnectionError
    """
    params = {
        "query": query,
        "start": _parse_iso_or_epoch(start),
        "end": _parse_iso_or_epoch(end),
        "step": step,
    }

    t0 = _time()
    data = _prom_request(endpoint, "/api/v1/query_range", params, timeout_sec)
    elapsed = int((_time() - t0) * 1000)

    raw_results = data.get("data", {}).get("result", [])
    series: list[RangeResultSeries] = []
    for item in raw_results:
        values = [(float(ts), float(val)) for ts, val in item.get("values", [])]
        series.append(RangeResultSeries(
            metric=item.get("metric", {}),
            values=values,
        ))

    return RangeResult(series=series, elapsed_ms=elapsed)


# ---------------------------------------------------------------------------
# 8.3 loki_log_query
# ---------------------------------------------------------------------------

def loki_log_query(
    *,
    endpoint: str,
    logql: str,
    limit: int = 1000,
    start: str | None = None,
    end: str | None = None,
    timeout_sec: int = 30,
) -> list[LogEntry]:
    """Loki LogQL 查询.

    Args:
        endpoint: Loki URL (e.g. "http://localhost:3100")
        logql: LogQL 表达式
        limit: 最多返回行数
        start: 起始时间 (ISO 8601), 默认 1h ago
        end: 截止时间 (ISO 8601), 默认 now
        timeout_sec: 请求超时

    Returns:
        LogEntry 列表

    Raises:
        OprimValidationError: LogQL 语法错
        OprimConnectionError
    """
    now = datetime.now(UTC)
    end_dt = now if end is None else datetime.fromisoformat(end.replace("Z", "+00:00"))
    start_dt = (end_dt - timedelta(hours=1)) if start is None else datetime.fromisoformat(
        start.replace("Z", "+00:00")
    )

    # Loki expects nanosecond timestamps
    start_ns = int(start_dt.timestamp() * 1e9)
    end_ns = int(end_dt.timestamp() * 1e9)

    url = endpoint.rstrip("/") + "/loki/api/v1/query_range"
    loki_params: dict[str, Any] = {
        "query": logql,
        "limit": limit,
        "start": start_ns,
        "end": end_ns,
        "direction": "forward",
    }

    try:
        resp = httpx.get(url, params=loki_params, timeout=timeout_sec)
    except httpx.ConnectError as exc:
        raise OprimConnectionError(f"Cannot reach Loki at {endpoint}: {exc}") from exc
    except httpx.TimeoutException as exc:
        raise OprimConnectionError(f"Loki request timed out: {exc}") from exc

    if resp.status_code == 400:
        data = resp.json()
        raise OprimValidationError(f"LogQL error: {data.get('error', resp.text[:200])}")
    if not resp.is_success:
        raise OprimConnectionError(f"Loki returned {resp.status_code}: {resp.text[:200]}")

    body = resp.json()
    result: list[LogEntry] = []
    for stream in body.get("data", {}).get("result", []):
        labels: dict[str, str] = stream.get("stream", {})
        for ts_ns, msg in stream.get("values", []):
            # Convert ns timestamp to ISO 8601
            ts_sec = int(ts_ns) / 1e9
            iso_ts = datetime.fromtimestamp(ts_sec, tz=UTC).isoformat()
            result.append(LogEntry(
                timestamp=iso_ts,
                labels=labels,
                message=msg,
            ))
    return result


# ---------------------------------------------------------------------------
# 8.4 structlog_parse
# ---------------------------------------------------------------------------

def structlog_parse(
    *,
    raw_lines: list[str],
    fmt: Literal["json", "logfmt"] = "json",
) -> list[dict[str, Any]]:
    """解析 structlog 输出 (纯本地函数, 不访问外部).

    Args:
        raw_lines: 原始日志行列表
        fmt: "json" (一行一 JSON) 或 "logfmt" (key=value 空格分隔)

    Returns:
        每行解析为一个 dict, 解析失败的行返 {"_raw": line, "_parse_error": "..."}
    """
    result: list[dict[str, Any]] = []
    for line in raw_lines:
        line = line.rstrip("\n")
        if not line:
            continue
        parsed = _parse_json_line(line) if fmt == "json" else _parse_logfmt_line(line)
        result.append(parsed)
    return result


def _parse_json_line(line: str) -> dict[str, Any]:
    try:
        return json.loads(line)  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        return {"_raw": line, "_parse_error": str(exc)}


def _parse_logfmt_line(line: str) -> dict[str, Any]:
    """Simple logfmt parser: key=value key2="quoted value" ..."""
    result: dict[str, Any] = {}
    i = 0
    n = len(line)
    while i < n:
        # Skip whitespace
        while i < n and line[i] == " ":
            i += 1
        if i >= n:
            break
        # Read key
        key_start = i
        while i < n and line[i] not in ("=", " "):
            i += 1
        key = line[key_start:i]
        if not key:
            i += 1
            continue
        if i >= n or line[i] != "=":
            result[key] = True
            continue
        i += 1  # skip '='
        if i >= n:
            result[key] = ""
            break
        # Read value
        if line[i] == '"':
            # Quoted value
            i += 1
            val_chars: list[str] = []
            while i < n:
                if line[i] == "\\" and i + 1 < n:
                    val_chars.append(line[i + 1])
                    i += 2
                elif line[i] == '"':
                    i += 1
                    break
                else:
                    val_chars.append(line[i])
                    i += 1
            result[key] = "".join(val_chars)
        else:
            val_start = i
            while i < n and line[i] != " ":
                i += 1
            result[key] = line[val_start:i]
    return result
