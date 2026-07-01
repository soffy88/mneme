"""Canonical event body for Ed25519 signing.

The signed payload excludes fields that are computed after signing or that
describe the signing operation itself. This matches the body that hash_current
is computed over in vcp_silver_record, minus conformance_tier.
"""
from __future__ import annotations

from oprim.serialization import canonical_json

SIGNATURE_EXCLUDED_FIELDS: frozenset[str] = frozenset({
    "signature",
    "signing_key_id",
    "conformance_tier",
    "hash_prev",
    "hash_current",
})


def canonical_event_body(event: dict) -> bytes:
    """Return canonical JSON bytes of *event* with signing-excluded fields removed.

    Parameters
    ----------
    event : dict
        Full VCP event dict (as returned by vcp_silver_record or fetched from DB).

    Returns
    -------
    bytes
        UTF-8 encoded canonical JSON, ready to pass to ed25519.sign().
    """
    body = {k: v for k, v in event.items() if k not in SIGNATURE_EXCLUDED_FIELDS}
    result = canonical_json(body)
    return result.encode() if isinstance(result, str) else result
