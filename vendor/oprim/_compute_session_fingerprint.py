"""Compute a deterministic fingerprint for a Session over a set of fields."""
from __future__ import annotations

from typing import Any

from obase import canonical_json, sha256_hash

from ._hicode_types import Session


def compute_session_fingerprint(session: Session, *, fields: set[str]) -> str:
    """Return a hex SHA-256 fingerprint of the specified session fields.

    Raises ValueError if fields is empty or if any requested field does not
    exist on the Session.
    """
    if not fields:
        raise ValueError("fields must not be empty")

    extracted: dict[str, Any] = {}
    for field_name in sorted(fields):
        if not hasattr(session, field_name):
            raise ValueError(f"Session has no field: {field_name!r}")
        extracted[field_name] = getattr(session, field_name)

    serialized: bytes = canonical_json(extracted)  # type: ignore[operator]
    digest: bytes = sha256_hash(serialized)  # type: ignore[operator]
    return digest.hex()
