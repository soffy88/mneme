"""RabbitMQ oprim — 4 atomic RabbitMQ Management API operations."""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel

from oprim._exceptions import (
    OprimAuthError,
    OprimConnectionError,
    OprimNotFoundError,
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class QueueStatus(BaseModel):
    name: str
    vhost: str
    messages: int
    messages_ready: int
    messages_unacked: int
    consumers: int
    state: Literal["running", "idle", "flow", "down"]
    memory_bytes: int
    disk_reads: int
    messages_persistent: int
    consumer_utilisation: float


class ConsumerInfo(BaseModel):
    consumer_tag: str
    channel: str
    queue: str
    prefetch_count: int
    ack_required: bool
    active: bool


class ConsumerStatus(BaseModel):
    queue_name: str
    consumer_count: int
    consumers: list[ConsumerInfo]


class ConnectionsStatus(BaseModel):
    total: int
    blocked: int
    running: int
    connections: list[dict[str, Any]]


class NodeStatus(BaseModel):
    name: str
    type: Literal["disc", "ram"]
    running: bool
    mem_used_bytes: int
    mem_limit_bytes: int
    mem_alarm: bool
    disk_free_bytes: int
    disk_free_limit_bytes: int
    disk_free_alarm: bool
    fd_used: int
    fd_total: int
    sockets_used: int
    sockets_total: int
    proc_used: int
    proc_total: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _mgmt_get(mgmt_url: str, path: str, timeout_sec: int) -> dict[str, Any] | list[Any]:
    """GET request to RabbitMQ management API; raise oprim-typed errors."""
    url = mgmt_url.rstrip("/") + "/" + path.lstrip("/")
    try:
        resp = httpx.get(url, timeout=timeout_sec)
    except httpx.ConnectError as exc:
        raise OprimConnectionError(
            f"Cannot reach RabbitMQ management API at {mgmt_url}: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise OprimConnectionError(f"Timeout connecting to RabbitMQ management API: {exc}") from exc

    if resp.status_code == 401:
        raise OprimAuthError("RabbitMQ authentication failed (HTTP 401)")
    if resp.status_code == 404:
        raise OprimNotFoundError(f"RabbitMQ resource not found: {path}")
    if not resp.is_success:
        raise OprimConnectionError(f"RabbitMQ API returned {resp.status_code}: {resp.text[:200]}")

    return resp.json()  # type: ignore[no-any-return]


def _encode_vhost(vhost: str) -> str:
    """URL-encode vhost, treating '/' as '%2F'."""
    return quote(vhost, safe="")


# ---------------------------------------------------------------------------
# 4.2 rabbitmq_queue_status
# ---------------------------------------------------------------------------


def rabbitmq_queue_status(
    *,
    mgmt_url: str,
    queue_name: str,
    vhost: str = "/",
    timeout_sec: int = 5,
) -> QueueStatus:
    """查队列状态.

    Args:
        mgmt_url: RabbitMQ Management API URL (e.g. "http://guest:guest@localhost:15672/api/")
        queue_name: 队列名称
        vhost: 虚拟主机, 默认 "/"
        timeout_sec: 请求超时

    Returns:
        QueueStatus

    Raises:
        OprimNotFoundError: 队列不存在
        OprimConnectionError / OprimAuthError
    """
    path = f"queues/{_encode_vhost(vhost)}/{quote(queue_name, safe='')}"
    data = _mgmt_get(mgmt_url, path, timeout_sec)
    assert isinstance(data, dict)

    raw_state = data.get("state", "running")
    valid_states = {"running", "idle", "flow", "down"}
    state = raw_state if raw_state in valid_states else "down"

    return QueueStatus(
        name=data.get("name", queue_name),
        vhost=data.get("vhost", vhost),
        messages=data.get("messages", 0),
        messages_ready=data.get("messages_ready", 0),
        messages_unacked=data.get("messages_unacknowledged", 0),
        consumers=data.get("consumers", 0),
        state=state,  # type: ignore[arg-type]
        memory_bytes=data.get("memory", 0),
        disk_reads=data.get("disk_reads", 0),
        messages_persistent=data.get("messages_persistent", 0),
        consumer_utilisation=data.get("consumer_utilisation") or 0.0,
    )


# ---------------------------------------------------------------------------
# 4.3 rabbitmq_connection_status
# ---------------------------------------------------------------------------


def rabbitmq_connection_status(
    *,
    mgmt_url: str,
    timeout_sec: int = 5,
) -> ConnectionsStatus:
    """查 broker 上所有连接状态.

    Args:
        mgmt_url: RabbitMQ Management API URL
        timeout_sec: 请求超时

    Returns:
        ConnectionsStatus

    Raises:
        OprimConnectionError / OprimAuthError
    """
    data = _mgmt_get(mgmt_url, "connections", timeout_sec)
    assert isinstance(data, list)

    connections = [
        {
            "name": c.get("name"),
            "state": c.get("state"),
            "channels": c.get("channels", 0),
            "recv_oct": c.get("recv_oct", 0),
            "send_oct": c.get("send_oct", 0),
            "peer_host": c.get("peer_host"),
            "user": c.get("user"),
        }
        for c in data
    ]
    blocked = sum(1 for c in data if c.get("state") == "blocked")
    running = sum(1 for c in data if c.get("state") == "running")

    return ConnectionsStatus(
        total=len(data),
        blocked=blocked,
        running=running,
        connections=connections,
    )


# ---------------------------------------------------------------------------
# 4.4 rabbitmq_consumer_status
# ---------------------------------------------------------------------------


def rabbitmq_consumer_status(
    *,
    mgmt_url: str,
    queue_name: str,
    vhost: str = "/",
    timeout_sec: int = 5,
) -> ConsumerStatus:
    """查指定队列的 consumer 列表.

    Args:
        mgmt_url: RabbitMQ Management API URL
        queue_name: 队列名称
        vhost: 虚拟主机
        timeout_sec: 请求超时

    Returns:
        ConsumerStatus

    Raises:
        OprimNotFoundError / OprimConnectionError / OprimAuthError
    """
    path = f"consumers/{_encode_vhost(vhost)}"
    data = _mgmt_get(mgmt_url, path, timeout_sec)
    assert isinstance(data, list)

    queue_consumers = [c for c in data if c.get("queue", {}).get("name") == queue_name]

    consumers = [
        ConsumerInfo(
            consumer_tag=c.get("consumer_tag", ""),
            channel=c.get("channel_details", {}).get("name", ""),
            queue=c.get("queue", {}).get("name", ""),
            prefetch_count=c.get("prefetch_count", 0),
            ack_required=c.get("ack_required", True),
            active=c.get("active", True),
        )
        for c in queue_consumers
    ]

    return ConsumerStatus(
        queue_name=queue_name,
        consumer_count=len(consumers),
        consumers=consumers,
    )


# ---------------------------------------------------------------------------
# 4.5 rabbitmq_node_status
# ---------------------------------------------------------------------------


def rabbitmq_node_status(
    *,
    mgmt_url: str,
    timeout_sec: int = 5,
) -> list[NodeStatus]:
    """查 broker 所有节点状态 (集群时多个).

    Args:
        mgmt_url: RabbitMQ Management API URL
        timeout_sec: 请求超时

    Returns:
        NodeStatus 列表

    Raises:
        OprimConnectionError / OprimAuthError
    """
    data = _mgmt_get(mgmt_url, "nodes", timeout_sec)
    assert isinstance(data, list)

    result = []
    for n in data:
        node_type = n.get("type", "disc")
        result.append(
            NodeStatus(
                name=n.get("name", ""),
                type="disc" if node_type not in ("disc", "ram") else node_type,
                running=bool(n.get("running", False)),
                mem_used_bytes=n.get("mem_used", 0),
                mem_limit_bytes=n.get("mem_limit", 0),
                mem_alarm=n.get("mem_alarm", False),
                disk_free_bytes=n.get("disk_free", 0),
                disk_free_limit_bytes=n.get("disk_free_limit", 0),
                disk_free_alarm=n.get("disk_free_alarm", False),
                fd_used=n.get("fd_used", 0),
                fd_total=n.get("fd_total", 0),
                sockets_used=n.get("sockets_used", 0),
                sockets_total=n.get("sockets_total", 0),
                proc_used=n.get("proc_used", 0),
                proc_total=n.get("proc_total", 0),
            )
        )
    return result


# ---------------------------------------------------------------------------
# Aegis IMPL SPEC v1.0 — focused single-value wrappers (B2)
# ---------------------------------------------------------------------------


def rabbitmq_queue_depth(
    *,
    mgmt_url: str,
    queue_name: str,
    vhost: str = "/",
    timeout_sec: int = 5,
) -> int:
    """返回队列深度 (messages ready + unacked).

    Args:
        mgmt_url: RabbitMQ Management API URL
        queue_name: 队列名称
        vhost: 虚拟主机
        timeout_sec: 请求超时

    Returns:
        队列中消息总数 (messages_ready + messages_unacknowledged)

    Raises:
        OprimNotFoundError / OprimConnectionError / OprimAuthError
    """
    status = rabbitmq_queue_status(
        mgmt_url=mgmt_url,
        queue_name=queue_name,
        vhost=vhost,
        timeout_sec=timeout_sec,
    )
    return status.messages_ready + status.messages_unacked


def rabbitmq_consumer_count(
    *,
    mgmt_url: str,
    queue_name: str,
    vhost: str = "/",
    timeout_sec: int = 5,
) -> int:
    """返回队列活跃消费者数量.

    Args:
        mgmt_url: RabbitMQ Management API URL
        queue_name: 队列名称
        vhost: 虚拟主机
        timeout_sec: 请求超时

    Returns:
        消费者数量 (int)

    Raises:
        OprimNotFoundError / OprimConnectionError / OprimAuthError
    """
    status = rabbitmq_queue_status(
        mgmt_url=mgmt_url,
        queue_name=queue_name,
        vhost=vhost,
        timeout_sec=timeout_sec,
    )
    return status.consumers
