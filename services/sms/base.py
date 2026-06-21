from abc import ABC, abstractmethod


class SMSProvider(ABC):
    @abstractmethod
    async def send_code(self, phone: str, code: str) -> bool:
        """Send verification code to phone. Returns True on success."""
        ...
