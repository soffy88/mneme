import logging
import os

from services.sms.base import SMSProvider

logger = logging.getLogger(__name__)


class MockSMSProvider(SMSProvider):
    """Development mock: logs the code instead of sending a real SMS.

    门控（C2/C5 配套）：仅 demo/dev 环境（MNEME_ENV != prod）可用。
    生产即使误配 SMS_PROVIDER=mock 也拒绝放行（fail-closed），
    与 main._assert_prod_safety 双重把关——不落日志、不发万能码。
    """

    def _prod_gate(self) -> bool:
        return os.environ.get("MNEME_ENV", "dev").lower() == "prod"

    async def send_code(self, phone: str, code: str) -> bool:
        if self._prod_gate():
            logger.error("[MockSMS] 生产环境禁用 mock provider，拒绝发送")
            return False
        logger.info(f"[MockSMS] phone={phone} code={code}")
        return True
