import logging

from services.feishu.base import FeishuProvider

logger = logging.getLogger(__name__)


class MockFeishuProvider(FeishuProvider):
    """开发/测试用 mock：只记日志，不真实调用飞书 webhook。"""

    async def send_message(self, webhook_url: str, text: str) -> bool:
        logger.info(f"[MockFeishu] webhook={webhook_url[-8:]} text={text!r}")
        return True
