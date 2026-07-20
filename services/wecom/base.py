from abc import ABC, abstractmethod


class WecomProvider(ABC):
    @abstractmethod
    async def send_message(self, webhook_url: str, text: str) -> bool:
        """向企业微信群机器人 webhook 推送一条文本消息。成功返回 True。"""
        ...
