"""redact_secret — replace known secret strings inside text."""
from __future__ import annotations


def redact_secret(text: str, *, secrets: list[str]) -> str:
    """Return *text* with every non-empty entry in *secrets* replaced by ``[REDACTED]``.

    All occurrences of each secret are replaced.  Empty-string secrets are
    skipped.  The replacement is applied left-to-right in list order.
    """
    for secret in secrets:
        if not secret:
            continue
        text = text.replace(secret, "[REDACTED]")
    return text
