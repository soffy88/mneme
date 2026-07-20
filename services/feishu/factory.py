import os

from services.feishu.base import FeishuProvider
from services.feishu.mock_provider import MockFeishuProvider
from services.feishu.webhook_provider import FeishuWebhookProvider


def get_feishu_provider() -> FeishuProvider:
    """按 FEISHU_PROVIDER 环境变量返回 provider（默认 mock）。webhook 目标 URL 由
    调用方按学生绑定传入，不在这里配置——同一 provider 服务所有群。"""
    name = os.environ.get("FEISHU_PROVIDER", "mock").lower()
    if name == "webhook":
        return FeishuWebhookProvider()
    return MockFeishuProvider()
