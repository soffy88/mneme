from __future__ import annotations

import time
from datetime import UTC, datetime

import pyotp
from pydantic import BaseModel


class OTPResult(BaseModel):
    secret: str
    code: str
    expires_at: datetime


def otp_generate(
    *,
    secret: str | None = None,
    digits: int = 6,
    period: int = 30,
) -> OTPResult:
    """Generate a TOTP code. Wraps obase.auth.totp_* logic via pyotp (REUSE).

    obase.auth.totp delegates directly to pyotp; this module reuses the same
    logic inline to avoid the obase.auth package-level argon2 dependency.

    Args:
        secret: Base32 TOTP secret. If None, generates a new one.
        digits: OTP digits (default 6)
        period: Time period in seconds (default 30)

    Returns:
        OTPResult with secret, current code, and expiry

    Example:
        >>> result = otp_generate()
        >>> len(result.code) == 6
        True
    """
    if secret is None:
        secret = pyotp.random_base32()

    totp = pyotp.TOTP(secret, digits=digits, interval=period)
    code = totp.now()

    # Calculate when current period expires
    now_ts = time.time()
    expires_at = datetime.fromtimestamp((int(now_ts // period) + 1) * period, tz=UTC)

    return OTPResult(secret=secret, code=code, expires_at=expires_at)


def otp_verify(*, secret: str, code: str) -> bool:
    """Verify a TOTP code against a secret.

    Reuses pyotp.TOTP.verify (same as obase.auth.totp_verify) with a 1-window
    tolerance to handle clock skew.

    Args:
        secret: Base32 TOTP secret
        code: TOTP code to verify

    Returns:
        True if code is valid for the current or adjacent time window
    """
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)
