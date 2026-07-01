"""Sentry-style error event fingerprint for issue aggregation (oprim 2.24.0)."""

from __future__ import annotations

import hashlib


def compute_event_fingerprint(
    *,
    exception_type: str,
    exception_value: str | None = None,
    top_frame_function: str | None = None,
    top_frame_filename: str | None = None,
    custom_fingerprint: list[str] | None = None,
) -> str:
    """Compute an error event fingerprint for Sentry-style issue aggregation.

    Same-type errors share a fingerprint → grouped into one issue.
    Callers can override grouping via custom_fingerprint.

    ⚠️ NOT omodul fingerprint (business transaction identity).
    ⚠️ NOT oprim.compute_dedup_key (time-bucket dedup).
    This is an error-attribute aggregation key, stable across time.

    Args:
        exception_type: Exception class name (e.g. "TypeError"). Must not be empty.
        exception_value: Exception message. None treated as "" for determinism.
        top_frame_function: Top stack frame function name. None treated as "".
        top_frame_filename: Top stack frame file path. None treated as "".
        custom_fingerprint: SDK-supplied grouping override. When provided, all
            other fields are ignored and this list is joined with null-bytes.

    Returns:
        SHA-256 hex digest (64 chars).

    Raises:
        ValueError: exception_type is empty string.

    Example:
        >>> fp = compute_event_fingerprint(
        ...     exception_type="TypeError",
        ...     exception_value="unsupported operand",
        ...     top_frame_function="process_payment",
        ...     top_frame_filename="aegis/payment.py",
        ... )
        >>> len(fp)
        64
        >>> # custom override
        >>> fp2 = compute_event_fingerprint(
        ...     exception_type="ValueError",
        ...     custom_fingerprint=["payment-flow", "retry-exhausted"],
        ... )
        >>> len(fp2)
        64
    """
    if not exception_type:
        raise ValueError("exception_type cannot be empty")

    if custom_fingerprint is not None:
        composite = "\x00".join(custom_fingerprint)
    else:
        composite = "\x00".join(
            [
                exception_type,
                exception_value or "",
                top_frame_function or "",
                top_frame_filename or "",
            ]
        )

    return hashlib.sha256(composite.encode("utf-8")).hexdigest()
