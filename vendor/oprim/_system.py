"""System resource oprim — 2 atomic system snapshot operations."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SystemSnapshot(BaseModel):
    host: str | None
    cpu_count: int
    cpu_percent: float
    cpu_percent_per_core: list[float]
    memory_total_bytes: int
    memory_available_bytes: int
    memory_used_bytes: int
    memory_percent: float
    swap_total_bytes: int
    swap_used_bytes: int
    load_avg_1m: float
    load_avg_5m: float
    load_avg_15m: float
    timestamp: str


class ProcessInfo(BaseModel):
    pid: int
    name: str
    cmdline: str
    cpu_percent: float
    memory_percent: float
    memory_rss_bytes: int
    status: str
    user: str | None


# ---------------------------------------------------------------------------
# 9.1 cpu_memory_snapshot
# ---------------------------------------------------------------------------


def cpu_memory_snapshot(
    *,
    host: str | None = None,
) -> SystemSnapshot:
    """系统 CPU + 内存快照.

    MVP: 仅支持本机. host != None 时 raise NotImplementedError.

    Args:
        host: None 表示本机; 传入值时 raise NotImplementedError (SSH 模式未实现)

    Returns:
        SystemSnapshot

    Raises:
        NotImplementedError: host is not None
    """
    if host is not None:
        raise NotImplementedError(
            "Remote host snapshot via SSH is not implemented in MVP. Pass host=None for local."
        )

    import psutil

    cpu_per_core: list[float] = psutil.cpu_percent(interval=0.1, percpu=True)
    cpu_avg = sum(cpu_per_core) / len(cpu_per_core) if cpu_per_core else 0.0

    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # getloadavg() not available on Windows
    try:
        load_1m, load_5m, load_15m = os.getloadavg()
    except (AttributeError, OSError):
        load_1m = load_5m = load_15m = 0.0

    return SystemSnapshot(
        host=None,
        cpu_count=psutil.cpu_count(logical=True) or 0,
        cpu_percent=round(cpu_avg, 2),
        cpu_percent_per_core=[round(p, 2) for p in cpu_per_core],
        memory_total_bytes=mem.total,
        memory_available_bytes=mem.available,
        memory_used_bytes=mem.used,
        memory_percent=round(mem.percent, 2),
        swap_total_bytes=swap.total,
        swap_used_bytes=swap.used,
        load_avg_1m=round(load_1m, 2),
        load_avg_5m=round(load_5m, 2),
        load_avg_15m=round(load_15m, 2),
        timestamp=datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# 9.2 process_list_top
# ---------------------------------------------------------------------------


def process_list_top(
    *,
    top_n: int = 20,
    sort_by: Literal["cpu", "mem"] = "cpu",
) -> list[ProcessInfo]:
    """top N 进程 (按 CPU 或内存排序).

    Args:
        top_n: 返回进程数量
        sort_by: 排序依据 ("cpu" 或 "mem")

    Returns:
        ProcessInfo 列表, 降序排列
    """
    import psutil

    procs: list[ProcessInfo] = []
    attrs = [
        "pid",
        "name",
        "cmdline",
        "cpu_percent",
        "memory_percent",
        "memory_info",
        "status",
        "username",
    ]
    for proc in psutil.process_iter(attrs):
        try:
            info = proc.info
            cmdline = " ".join(info.get("cmdline") or [])
            mem_info = info.get("memory_info")
            rss = mem_info.rss if mem_info else 0
            procs.append(
                ProcessInfo(
                    pid=info["pid"],
                    name=info.get("name") or "",
                    cmdline=cmdline[:500],
                    cpu_percent=round(info.get("cpu_percent") or 0.0, 2),
                    memory_percent=round(info.get("memory_percent") or 0.0, 2),
                    memory_rss_bytes=rss,
                    status=info.get("status") or "",
                    user=info.get("username"),
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    key = (lambda p: p.cpu_percent) if sort_by == "cpu" else (lambda p: p.memory_percent)
    procs.sort(key=key, reverse=True)
    return procs[:top_n]


# ---------------------------------------------------------------------------
# Aegis IMPL SPEC v1.0 — focused single-metric wrappers (B2)
# ---------------------------------------------------------------------------


def system_cpu_usage() -> float:
    """当前 CPU 使用率 (0.0 – 100.0).

    Returns:
        CPU 使用率百分比 (float, 0–100)
    """
    import psutil

    per_core: list[float] = psutil.cpu_percent(interval=0.1, percpu=True)
    return round(sum(per_core) / len(per_core), 2) if per_core else 0.0


def system_ram_usage() -> dict[str, int | float]:
    """当前内存使用情况.

    Returns:
        {
          "total_bytes": int,
          "used_bytes": int,
          "available_bytes": int,
          "used_percent": float,
        }
    """
    import psutil

    mem = psutil.virtual_memory()
    return {
        "total_bytes": mem.total,
        "used_bytes": mem.used,
        "available_bytes": mem.available,
        "used_percent": round(mem.percent, 2),
    }


def system_load_avg() -> dict[str, float]:
    """系统 1/5/15 分钟平均负载.

    Returns:
        {"load_1m": float, "load_5m": float, "load_15m": float}

    Note:
        Windows 上 os.getloadavg() 不可用, 返回全零.
    """
    import os

    try:
        l1, l5, l15 = os.getloadavg()
    except (AttributeError, OSError):
        l1 = l5 = l15 = 0.0
    return {
        "load_1m": round(l1, 2),
        "load_5m": round(l5, 2),
        "load_15m": round(l15, 2),
    }
