"""W5 PA-1：Partners 渠道注册表结构测试。

16 渠道登记齐全，仅 WeCom + Feishu 激活；未激活渠道调用显式抛
NotImplementedError（不会静默假装发送成功）；未知渠道抛 ValueError。
"""

from __future__ import annotations

import pytest

from services.partner_channels import CHANNEL_REGISTRY, send_via_channel


def test_exactly_sixteen_channels_registered():
    assert len(CHANNEL_REGISTRY) == 16


def test_only_wecom_and_feishu_active():
    active = {name for name, meta in CHANNEL_REGISTRY.items() if meta.active}
    assert active == {"wecom", "feishu"}


def test_personal_wechat_not_in_registry():
    """个人微信不做（未成年人数据产品 ToS/封号风险，用户已拍板）。"""
    assert "weixin" not in CHANNEL_REGISTRY  # 个人微信不是 "weixin_personal" 之外的别名
    assert CHANNEL_REGISTRY["weixin_personal"].active is False


@pytest.mark.asyncio
async def test_send_via_wecom_uses_mock_provider_by_default(monkeypatch):
    monkeypatch.delenv("WECOM_PROVIDER", raising=False)
    ok = await send_via_channel("wecom", "https://example.invalid/webhook/key", "hi")
    assert ok is True


@pytest.mark.asyncio
async def test_send_via_feishu_uses_mock_provider_by_default(monkeypatch):
    monkeypatch.delenv("FEISHU_PROVIDER", raising=False)
    ok = await send_via_channel("feishu", "https://example.invalid/webhook/key", "hi")
    assert ok is True


@pytest.mark.asyncio
async def test_send_via_inactive_channel_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        await send_via_channel("telegram", "target", "hi")


@pytest.mark.asyncio
async def test_send_via_unknown_channel_raises_value_error():
    with pytest.raises(ValueError):
        await send_via_channel("not-a-real-channel", "target", "hi")
