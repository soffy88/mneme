"""邮件 provider 层（mock + smtp 可插拔，镜像 SMS provider）。
SMTP 真实发送路径已用 Ethereal 免费临时账号端到端实证跑通（见提交说明），
这里只测 factory 选型 + mock 行为 + 脱敏，不在 CI 里真连外网 SMTP。"""

from __future__ import annotations

import pytest

from services.email import (
    EmailProvider,
    MockEmailProvider,
    SMTPEmailProvider,
    get_email_provider,
)
from services.email.smtp_provider import _mask_email


def test_factory_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    assert isinstance(get_email_provider(), MockEmailProvider)


def test_factory_returns_smtp_when_configured(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    prov = get_email_provider()
    assert isinstance(prov, SMTPEmailProvider)
    assert isinstance(prov, EmailProvider)


@pytest.mark.asyncio
async def test_mock_provider_returns_true():
    prov = MockEmailProvider()
    assert await prov.send_code("kid@example.com", "123456") is True


def test_mask_email():
    assert _mask_email("student@qq.com") == "s***@qq.com"
    assert _mask_email("not-an-email") == "***"
