import logging

from services.email.base import EmailProvider

logger = logging.getLogger(__name__)


class MockEmailProvider(EmailProvider):
    """开发 mock：把验证码打到日志，不真发邮件。"""

    async def send_code(self, email: str, code: str) -> bool:
        logger.info(f"[MockEmail] to={email} code={code}")
        return True
