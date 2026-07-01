"""Container swap oskill."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Literal

from oprim import (
    docker_container_inspect,
    docker_container_rename,
    docker_container_start,
    docker_container_stop,
)
from pydantic import BaseModel


class ContainerSwapResult(BaseModel):
    old_container_id: str
    new_container_id: str
    operation: Literal["deploy", "rollback"]
    old_name: str
    new_name: str
    elapsed_ms: int


def container_swap(
    *,
    active_container_id: str,  # 当前运行的容器
    standby_container_id: str,  # 要切换上去的容器
    service_name: str,  # 最终对外暴露的名称
    operation: Literal["deploy", "rollback"] = "deploy",
    stop_timeout_sec: int = 10,
    docker_host: str = "unix:///var/run/docker.sock",
) -> ContainerSwapResult:
    """原子地切换容器 (停止旧的, 改名, 启动新的)."""
    start_time = time.perf_counter()
    ts = int(datetime.now(UTC).timestamp())

    # 1. Inspect active to get its current name (though we likely know it)
    inspect_old = docker_container_inspect(
        container_id=active_container_id, docker_host=docker_host
    )
    old_name = inspect_old.name

    # 2. Stop active container
    docker_container_stop(
        container_id=active_container_id,
        timeout_sec=stop_timeout_sec,
        docker_host=docker_host,
    )

    # 3. Rename active to archive name
    archive_name = f"{service_name}-old-{ts}"
    docker_container_rename(
        container_id=active_container_id,
        new_name=archive_name,
        docker_host=docker_host,
    )

    # 4. Rename standby to primary name
    docker_container_rename(
        container_id=standby_container_id,
        new_name=service_name,
        docker_host=docker_host,
    )

    # 5. Start new active container
    docker_container_start(
        container_id=standby_container_id,
        docker_host=docker_host,
    )

    elapsed_ms = int((time.perf_counter() - start_time) * 1000)
    return ContainerSwapResult(
        old_container_id=active_container_id,
        new_container_id=standby_container_id,
        operation=operation,
        old_name=old_name,
        new_name=service_name,
        elapsed_ms=elapsed_ms,
    )
