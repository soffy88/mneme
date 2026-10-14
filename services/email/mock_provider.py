import logging
import os

from services.email.base import EmailProvider

logger = logging.getLogger(__name__)


class MockEmailProvider(EmailProvider):
    """开发 mock：把验证码打到日志，不真发邮件。

    固定验证码只对 dev/development/test 环境中显式 allowlist 的测试身份开放。
    demo 是公开环境，始终 fail-closed；不会向日志写验证码或正文。"""

    def _allowlisted(self, email: str) -> bool:
        env = os.environ.get("MNEME_ENV", "").strip().lower()
        allowlist = {
            item.strip().lower()
            for item in os.environ.get("MNEME_MOCK_CODE_ALLOWLIST", "").split(",")
            if item.strip()
        }
        return env in {"dev", "development", "test"} and email.strip().lower() in allowlist

    async def send_code(self, email: str, code: str) -> bool:
        if code == "123456" and self._allowlisted(email):
            local, _, domain = email.partition("@")
            masked = f"{local[:1]}***@{domain}" if domain else "***"
            logger.info("[MockEmail] test OTP issued to allowlisted identity %s", masked)
            return True
        logger.warning("[MockEmail] real email unavailable; refusing to log or deliver OTP")
        return False

    async def send_notification(self, email: str, title: str, content: str) -> bool:
        # Never write user message content to application logs in a public demo deployment.
        if os.environ.get("MNEME_ENV", "").strip().lower() not in {"dev", "development", "test"}:
            logger.warning("[MockEmail] notification delivery disabled outside local/test environments")
            return False
        logger.info("[MockEmail] notification suppressed for %s", email.partition("@")[0][:1] + "***")
        return True
