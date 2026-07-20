import os

from services.wecom.base import WecomProvider
from services.wecom.mock_provider import MockWecomProvider
from services.wecom.webhook_provider import WecomWebhookProvider


def get_wecom_provider() -> WecomProvider:
    """按 WECOM_PROVIDER 环境变量返回 provider（默认 mock）。webhook 目标 URL 由
    调用方按学生绑定传入，不在这里配置——同一 provider 服务所有群。"""
    name = os.environ.get("WECOM_PROVIDER", "mock").lower()
    if name == "webhook":
        return WecomWebhookProvider()
    return MockWecomProvider()
