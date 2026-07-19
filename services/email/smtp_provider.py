import asyncio
import logging
import smtplib
from email.mime.text import MIMEText

from services.email.base import EmailProvider

logger = logging.getLogger(__name__)


def _mask_email(email: str) -> str:
    """日志脱敏：a***@example.com。"""
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    head = local[0] if local else ""
    return f"{head}***@{domain}"


class SMTPEmailProvider(EmailProvider):
    """通用 SMTP 发信——适配任意免费邮件服务（QQ/163/Gmail/Brevo/Ethereal 等）。
    凭据全部走环境变量，不硬编码。smtplib 是同步的，用 to_thread 包成异步，
    与服务层全异步一致（不阻塞事件循环）。"""

    def __init__(
        self,
        *,
        host: str,
        port: int = 587,
        user: str = "",
        password: str = "",
        from_addr: str = "",
        use_tls: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from = from_addr or user
        self._use_tls = use_tls

    def _send_sync(self, email: str, code: str) -> None:
        body = f"你的善学记验证码是 {code}，5 分钟内有效。\n如非本人操作请忽略本邮件。"
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = "【善学记】邮箱验证码"
        msg["From"] = self._from
        msg["To"] = email
        with smtplib.SMTP(self._host, self._port, timeout=20) as server:
            if self._use_tls:
                server.starttls()
            if self._user and self._password:
                server.login(self._user, self._password)
            server.sendmail(self._from, [email], msg.as_string())

    def _send_notification_sync(self, email: str, title: str, content: str) -> None:
        msg = MIMEText(content, "plain", "utf-8")
        msg["Subject"] = title
        msg["From"] = self._from
        msg["To"] = email
        with smtplib.SMTP(self._host, self._port, timeout=20) as server:
            if self._use_tls:
                server.starttls()
            if self._user and self._password:
                server.login(self._user, self._password)
            server.sendmail(self._from, [email], msg.as_string())

    async def send_code(self, email: str, code: str) -> bool:
        try:
            await asyncio.to_thread(self._send_sync, email, code)
            logger.info(f"[SMTPEmail] sent to={_mask_email(email)} via={self._host}")
            return True
        except Exception as e:  # noqa: BLE001 — 发信失败不抛，返回 False 交上层处理
            logger.error(f"[SMTPEmail] send failed to={_mask_email(email)}: {e}")
            return False

    async def send_notification(self, email: str, title: str, content: str) -> bool:
        try:
            await asyncio.to_thread(self._send_notification_sync, email, title, content)
            logger.info(f"[SMTPEmail] notification sent to={_mask_email(email)} via={self._host}")
            return True
        except Exception as e:
            logger.error(f"[SMTPEmail] notification failed to={_mask_email(email)}: {e}")
            return False
