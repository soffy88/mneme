import os
from services.sms.base import SMSProvider
from services.sms.mock_provider import MockSMSProvider
from services.sms.aliyun_provider import AliyunSMSProvider


def get_sms_provider() -> SMSProvider:
    """Return the configured SMS provider based on SMS_PROVIDER env var (default: mock)."""
    name = os.environ.get("SMS_PROVIDER", "mock").lower()
    if name == "aliyun":
        return AliyunSMSProvider(
            access_key_id=os.environ.get("ALIYUN_ACCESS_KEY_ID", ""),
            access_key_secret=os.environ.get("ALIYUN_ACCESS_KEY_SECRET", ""),
            sign_name=os.environ.get("SMS_SIGN_NAME", ""),
            template_code=os.environ.get("SMS_TEMPLATE_CODE", ""),
        )
    return MockSMSProvider()
