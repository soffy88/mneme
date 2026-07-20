import logging

import httpx

from services.feishu.base import FeishuProvider

logger = logging.getLogger(__name__)


class FeishuWebhookProvider(FeishuProvider):
    """飞书群机器人 webhook——push-only，零资质路径（群设置里加自定义机器人即得
    webhook URL，无需企业认证）。每次推送目标群由调用方传入的 webhook_url 决定，
    本 provider 不持有固定凭据。
    """

    async def send_message(self, webhook_url: str, text: str) -> bool:
        payload = {"msg_type": "text", "content": {"text": text}}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(webhook_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:  # noqa: BLE001 — 推送失败不抛，返回 False 交上层处理
            logger.error(f"[FeishuWebhook] send failed: {e}")
            return False

        # 飞书新旧两代自定义机器人 API 成功码字段不同（code=0 / StatusCode=0）。
        ok = data.get("code", data.get("StatusCode", -1)) == 0
        if not ok:
            logger.error(f"[FeishuWebhook] send rejected: {data}")
        return ok
