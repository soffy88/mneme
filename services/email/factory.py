import os

from services.email.base import EmailProvider
from services.email.mock_provider import MockEmailProvider
from services.email.smtp_provider import SMTPEmailProvider


def get_email_provider() -> EmailProvider:
    """按 EMAIL_PROVIDER 环境变量返回邮件 provider（默认 mock）。
    smtp 模式凭据全走环境变量，适配任意免费 SMTP 服务。"""
    name = os.environ.get("EMAIL_PROVIDER", "mock").lower()
    if name == "smtp":
        return SMTPEmailProvider(
            host=os.environ.get("SMTP_HOST", ""),
            port=int(os.environ.get("SMTP_PORT", "587")),
            user=os.environ.get("SMTP_USER", ""),
            password=os.environ.get("SMTP_PASSWORD", ""),
            from_addr=os.environ.get("SMTP_FROM", ""),
            use_tls=os.environ.get("SMTP_USE_TLS", "true").lower() != "false",
        )
    return MockEmailProvider()
