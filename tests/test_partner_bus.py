"""W5 A2：Partner 事件总线（obase.partner_bus）单元测试。

纯 in-process asyncio.Queue 对，无外部 broker——验证 publish/consume 往返、
每个实例独立（不是全局单例）、inbound/outbound 互不干扰。
"""

from __future__ import annotations

import pytest

from obase.partner_bus import InboundMessage, OutboundMessage, PartnerMessageBus


@pytest.mark.asyncio
async def test_outbound_publish_consume_roundtrip():
    bus = PartnerMessageBus()
    msg = OutboundMessage(channel="wecom", chat_id="group-1", content="hello")
    await bus.publish_outbound(msg)
    assert bus.outbound_size == 1

    got = await bus.consume_outbound()
    assert got is msg
    assert bus.outbound_size == 0


@pytest.mark.asyncio
async def test_inbound_publish_consume_roundtrip():
    bus = PartnerMessageBus()
    msg = InboundMessage(channel="wecom", sender_id="u1", chat_id="c1", content="hi")
    await bus.publish_inbound(msg)
    assert bus.inbound_size == 1

    got = await bus.consume_inbound()
    assert got is msg
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_each_instance_is_independent_not_a_global_singleton():
    bus_a = PartnerMessageBus()
    bus_b = PartnerMessageBus()
    await bus_a.publish_outbound(
        OutboundMessage(channel="wecom", chat_id="c", content="x")
    )
    assert bus_a.outbound_size == 1
    assert bus_b.outbound_size == 0
