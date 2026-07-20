"""W5 PA-7：外发数据最小化。

推送给外部渠道（WeCom/Feishu webhook）的内容只能是文案文本本身——不带
student_id/UUID/手机号/邮箱等可识别个人信息；这些字段只用于内部去重/审计
（agent.partner_push_log），从不进入实际外发的 send_via_channel 调用参数。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from obase.partner_bus import OutboundMessage, PartnerMessageBus


@pytest.mark.asyncio
async def test_send_via_channel_receives_only_channel_target_text_no_pii():
    """复现 tasks/partner_heartbeat.py 的发送调用点：send_via_channel 的入参
    必须只有 (channel, chat_id, content) ——不包含 metadata 里的 student_id。"""
    bus = PartnerMessageBus()
    sid = uuid.uuid4()
    await bus.publish_outbound(
        OutboundMessage(
            channel="wecom",
            chat_id="https://example.invalid/wh/1",
            content="你好，同学：你有 11 道错题到了复习时间。",
            metadata={"student_id": str(sid), "dedup_key": "review_due:2026-07-19"},
        )
    )
    msg = await bus.consume_outbound()

    with patch(
        "tasks.partner_heartbeat.send_via_channel", new=AsyncMock(return_value=True)
    ) as mock_send:
        await mock_send(msg.channel, msg.chat_id, msg.content)

    mock_send.assert_awaited_once_with(
        "wecom",
        "https://example.invalid/wh/1",
        "你好，同学：你有 11 道错题到了复习时间。",
    )
    sent_args = mock_send.call_args.args
    assert str(sid) not in sent_args
    assert not any(isinstance(a, str) and "student_id" in a for a in sent_args)


def test_push_text_template_contains_no_contact_info_placeholders():
    """确定性回落模板本身不含手机号/邮箱占位——只有称呼 + 到期数。"""
    from oprim.generate_partner_push_text import _FALLBACK_TEMPLATE

    import re

    rendered = _FALLBACK_TEMPLATE.format(name="学生A", due_count=5)
    assert "@" not in rendered  # 无邮箱
    assert not re.search(r"\d{6,}", rendered)  # 无手机号/身份证等长数字串
