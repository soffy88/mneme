from abc import ABC, abstractmethod


class EmailProvider(ABC):
    @abstractmethod
    async def send_code(self, email: str, code: str) -> bool:
        """发送验证码到邮箱。成功返回 True。"""
        ...
