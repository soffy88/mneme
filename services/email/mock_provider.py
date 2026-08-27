import logging
import os

from services.email.base import EmailProvider

logger = logging.getLogger(__name__)


class MockEmailProvider(EmailProvider):
    """开发 mock：把验证码打到日志，不真发邮件。

    门控（C2/C5 配套）：仅 demo/dev 环境（MNEME_ENV != prod）可用；
    生产误配 EMAIL_PROVIDER=mock 时 fail-closed（不发验证码日志）。"""

    def _prod_gate(self) -> bool:
        return os.environ.get("MNEME_ENV", "dev").lower() in {"prod", "production"}

    async def send_code(self, email: str, code: str) -> bool:
        if self._prod_gate():
            logger.error("[MockEmail] 生产环境禁用 mock provider，拒绝发送")
            return False
        logger.info("[MockEmail] 发送验证码给 %s, 验证码: %s", email, code)
        return True

    async def send_notification(self, email: str, title: str, content: str) -> bool:
        if self._prod_gate():
            logger.error("[MockEmail] 生产环境禁用 mock provider，拒绝发送")
            return False
        logger.info("[MockEmail] 发送通知给 %s, 标题: %s, 内容: %s", email, title, content)
        return True
