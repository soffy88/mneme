import logging
import os

from services.sms.base import SMSProvider

logger = logging.getLogger(__name__)


class MockSMSProvider(SMSProvider):
    """Development mock: logs the code instead of sending a real SMS.

    固定码只对 dev/development/test 中的精确 allowlist 身份开放。
    demo 是公开环境；误配 mock 时 fail-closed，绝不记录验证码或手机号。
    """

    def _prod_gate(self) -> bool:
        """Compatibility helper; demo traffic is production-facing too."""
        return os.environ.get("MNEME_ENV", "").strip().lower() in {"prod", "production", "demo"}

    def _allowlisted(self, phone: str) -> bool:
        env = os.environ.get("MNEME_ENV", "").strip().lower()
        allowlist = {
            item.strip().lower()
            for item in os.environ.get("MNEME_MOCK_CODE_ALLOWLIST", "").split(",")
            if item.strip()
        }
        return env in {"dev", "development", "test"} and phone.strip().lower() in allowlist

    async def send_code(self, phone: str, code: str) -> bool:
        if code == "123456" and self._allowlisted(phone):
            logger.info("[MockSMS] test OTP issued to explicitly allowlisted test identity")
            return True
        logger.warning("[MockSMS] real SMS unavailable; refusing to log or deliver OTP")
        return False
