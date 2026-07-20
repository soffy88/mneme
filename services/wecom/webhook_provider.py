import logging

import httpx

from services.wecom.base import WecomProvider

logger = logging.getLogger(__name__)


class WecomWebhookProvider(WecomProvider):
    """企业微信群机器人 webhook——push-only，零资质路径（群管理员加机器人即得
    webhook URL，含 key，无需企业认证）。每次推送目标群由调用方传入的
    webhook_url 决定，本 provider 不持有固定凭据。
    """

    async def send_message(self, webhook_url: str, text: str) -> bool:
        payload = {"msgtype": "text", "text": {"content": text}}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(webhook_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:  # noqa: BLE001 — 推送失败不抛，返回 False 交上层处理
            logger.error(f"[WecomWebhook] send failed: {e}")
            return False

        if data.get("errcode") != 0:
            logger.error(f"[WecomWebhook] send rejected: {data}")
            return False
        return True
