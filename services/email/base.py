from abc import ABC, abstractmethod


class EmailProvider(ABC):
    @abstractmethod
    async def send_code(self, email: str, code: str) -> bool:
        """发送验证码到邮箱。成功返回 True。"""
        ...

    @abstractmethod
    async def send_notification(self, email: str, title: str, content: str) -> bool:
        """发送普通通知到邮箱。成功返回 True。"""
        ...
