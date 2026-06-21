import logging
from services.sms.base import SMSProvider

logger = logging.getLogger(__name__)


class MockSMSProvider(SMSProvider):
    """Development mock: logs the code instead of sending a real SMS."""

    async def send_code(self, phone: str, code: str) -> bool:
        logger.info(f"[MockSMS] phone={phone} code={code}")
        return True
