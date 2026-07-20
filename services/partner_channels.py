"""services.partner_channels — Partners 渠道注册表（W5 A1）。

16 渠道全部登记（结构完整，覆盖面可审查），仅 WeCom + Feishu 激活——群 webhook
bot，push-only，零资质路径（盘点 W5-PREWORK-INVENTORY-001 确认可行）。其余 14
个挂着待启，不接真实 SDK/凭据；调用未激活渠道显式抛错，不会静默假装发送成功。
个人微信不在册（未成年人数据产品 ToS/封号风险，用户已拍板不做）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from services.feishu import get_feishu_provider
from services.wecom import get_wecom_provider


@dataclass(frozen=True)
class ChannelMeta:
    name: str
    display_name: str
    active: bool


# 16 渠道（非 18，盘点纠正）。telegram 原计划首发，盘点显示国内场景 WeCom/Feishu
# 更实，降为注册表待启。
CHANNEL_REGISTRY: dict[str, ChannelMeta] = {
    "wecom": ChannelMeta("wecom", "企业微信", active=True),
    "feishu": ChannelMeta("feishu", "飞书", active=True),
    "telegram": ChannelMeta("telegram", "Telegram", active=False),
    "slack": ChannelMeta("slack", "Slack", active=False),
    "dingtalk": ChannelMeta("dingtalk", "钉钉", active=False),
    "qq": ChannelMeta("qq", "QQ", active=False),
    "matrix": ChannelMeta("matrix", "Matrix", active=False),
    "zulip": ChannelMeta("zulip", "Zulip", active=False),
    "napcat": ChannelMeta("napcat", "NapCat", active=False),
    "whatsapp": ChannelMeta("whatsapp", "WhatsApp", active=False),
    "mochat": ChannelMeta("mochat", "MoChat", active=False),
    "discord": ChannelMeta("discord", "Discord", active=False),
    "mattermost": ChannelMeta("mattermost", "Mattermost", active=False),
    "msteams": ChannelMeta("msteams", "Microsoft Teams", active=False),
    "weixin_personal": ChannelMeta("weixin_personal", "个人微信", active=False),
    "email": ChannelMeta("email", "邮件", active=False),
}

assert len(CHANNEL_REGISTRY) == 16, "渠道注册表应恰好 16 个（盘点纠正后的数字）"


def _wecom_send(webhook_url: str, text: str) -> Awaitable[bool]:
    return get_wecom_provider().send_message(webhook_url, text)


def _feishu_send(webhook_url: str, text: str) -> Awaitable[bool]:
    return get_feishu_provider().send_message(webhook_url, text)


_ACTIVE_SENDERS: dict[str, Callable[[str, str], Awaitable[bool]]] = {
    "wecom": _wecom_send,
    "feishu": _feishu_send,
}


async def send_via_channel(channel: str, webhook_url: str, text: str) -> bool:
    """经指定渠道推送一条文本消息。

    渠道不在注册表 → ValueError；渠道已登记但未激活 → NotImplementedError
    （不会静默假装发送成功，调用方必须显式处理"这条渠道还没做"）。
    """
    meta = CHANNEL_REGISTRY.get(channel)
    if meta is None:
        raise ValueError(f"unknown partner channel: {channel!r}")
    if not meta.active:
        raise NotImplementedError(
            f"partner channel {channel!r} 已登记但未激活（W5 v1 只激活 wecom/feishu）"
        )
    return await _ACTIVE_SENDERS[channel](webhook_url, text)
