from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from pydantic import BaseModel

from oprim._exceptions import OprimError


class EmailResult(BaseModel):
    success: bool
    to: str
    subject: str
    error: str | None = None


def push_email(
    *,
    to: str,
    subject: str,
    body: str,
    from_addr: str,
    smtp_host: str,
    smtp_port: int = 587,
    smtp_user: str | None = None,
    smtp_password: str | None = None,
    use_tls: bool = True,
    html_body: str | None = None,
) -> EmailResult:
    """Send a single email via SMTP.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Plain text body
        from_addr: Sender email address
        smtp_host: SMTP server hostname
        smtp_port: SMTP server port (default 587 for STARTTLS)
        smtp_user: SMTP authentication username (optional)
        smtp_password: SMTP authentication password (optional)
        use_tls: Use STARTTLS (default True)
        html_body: Optional HTML body (sends multipart if provided)

    Returns:
        EmailResult with success status

    Raises:
        OprimError: SMTP connection failed or authentication error

    Example:
        >>> result = push_email(to="user@example.com", subject="Welcome",
        ...     body="Hello!", from_addr="noreply@example.com",
        ...     smtp_host="smtp.example.com")
        >>> result.success
        True
    """
    try:
        if html_body:
            msg: MIMEMultipart | MIMEText = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_addr
            msg["To"] = to
            assert isinstance(msg, MIMEMultipart)
            msg.attach(MIMEText(body, "plain"))
            msg.attach(MIMEText(html_body, "html"))
        else:
            msg = MIMEText(body, "plain")
            msg["Subject"] = subject
            msg["From"] = from_addr
            msg["To"] = to

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if use_tls:
                server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.sendmail(from_addr, [to], msg.as_string())

        return EmailResult(success=True, to=to, subject=subject)

    except smtplib.SMTPException as e:
        raise OprimError(f"push_email SMTP error: {e}") from e
    except OSError as e:
        raise OprimError(f"push_email connection failed: {e}") from e
