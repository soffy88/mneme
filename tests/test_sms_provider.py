"""SMS provider 层（镜像 test_email_provider.py）：mock 行为 + 生产 fail-closed 门控。"""

from __future__ import annotations

import pytest

from services.sms import MockSMSProvider, get_sms_provider
from services.sms.mock_provider import MockSMSProvider as MockImpl


def test_factory_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("SMS_PROVIDER", raising=False)
    assert isinstance(get_sms_provider(), MockSMSProvider)


def test_factory_returns_aliyun_when_configured(monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER", "aliyun")
    prov = get_sms_provider()
    assert type(prov).__name__ == "AliyunSMSProvider"


@pytest.mark.asyncio
async def test_mock_provider_returns_true():
    prov = MockSMSProvider()
    assert await prov.send_code("13912345678", "123456") is True


@pytest.mark.asyncio
async def test_mock_provider_fail_closed_in_prod(monkeypatch):
    """C2/C5：生产误配 SMS_PROVIDER=mock 必须 fail-closed——不发万能码。"""
    monkeypatch.setenv("MNEME_ENV", "prod")
    prov = MockSMSProvider()
    assert await prov.send_code("13912345678", "123456") is False


def test_prod_gate_true_in_prod(monkeypatch):
    monkeypatch.setenv("MNEME_ENV", "prod")
    assert MockImpl()._prod_gate() is True


def test_prod_gate_false_in_dev(monkeypatch):
    monkeypatch.setenv("MNEME_ENV", "dev")
    assert MockImpl()._prod_gate() is False
