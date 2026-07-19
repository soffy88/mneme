import logging

from services.email.base import EmailProvider

logger = logging.getLogger(__name__)


class MockEmailProvider(EmailProvider):
    """开发 mock：把验证码打到日志，不真发邮件。"""

    async def send_code(self, email: str, code: str) -> bool:
        logger.info("[MockEmail] 发送验证码给 %s, 验证码: %s", email, code)
        return True

    async def send_notification(self, email: str, title: str, content: str) -> bool:
        logger.info("[MockEmail] 发送通知给 %s, 标题: %s, 内容: %s", email, title, content)
        return True
