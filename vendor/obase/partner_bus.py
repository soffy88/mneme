"""obase.partner_bus — Partners 进程内事件总线（W5 A2）。

纯 in-process asyncio.Queue 对，无外部 broker（照搬 DeepTutor partners/bus 设计，
用户已拍板：不引 broker）。每个 Partner 一个 PartnerMessageBus 实例（不是全局
单例）——W5 v1 push-only，只用 outbound 侧；inbound 侧为未来双向入站预留形状，
暂无生产者，进程崩溃丢队列内消息是可接受的（IM 渠道本身会重投/学生会重新发）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class InboundMessage:
    """未来双向入站预留形状——W5 v1 无生产者。"""

    channel: str
    sender_id: str
    chat_id: str
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutboundMessage:
    channel: str
    chat_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class PartnerMessageBus:
    """一个 Partner 一份实例，inbound/outbound 两条独立队列。"""

    def __init__(self) -> None:
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        return self.outbound.qsize()
