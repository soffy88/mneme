import logging

from services.wecom.base import WecomProvider

logger = logging.getLogger(__name__)


class MockWecomProvider(WecomProvider):
    """开发/测试用 mock：只记日志，不真实调用企业微信 webhook。"""

    async def send_message(self, webhook_url: str, text: str) -> bool:
        logger.info(f"[MockWecom] webhook={webhook_url[-8:]} text={text!r}")
        return True
