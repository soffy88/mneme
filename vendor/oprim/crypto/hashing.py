"""Cryptographic hash primitives (stdlib only)."""

from __future__ import annotations

import hashlib
import hmac as _hmac


def sha256_hash(data: bytes | str) -> str:
    """SHA-256 cryptographic hash.

    If input is str, encode as UTF-8 before hashing.
    Returns lowercase hex string of exactly 64 characters.

    Mathematical definition: NIST FIPS 180-4 SHA-256.

    Reference: NIST FIPS 180-4 (2015).
    https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.180-4.pdf

    Parameters
    ----------
    data : bytes or str
        Input to hash. str is UTF-8 encoded; bytes hashed directly.

    Returns
    -------
    str
        64-character lowercase hex string.

    Raises
    ------
    TypeError
        If data is not bytes or str.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    elif not isinstance(data, (bytes, bytearray)):
        raise TypeError(f"data must be bytes or str, got {type(data).__name__}")
    return hashlib.sha256(data).hexdigest()


def hmac_sha256(key: bytes, data: bytes | str) -> str:
    """HMAC-SHA-256.

    Mathematical definition: RFC 2104 HMAC construction with SHA-256.
    Returns lowercase hex string of exactly 64 characters.

    Reference: RFC 2104 (1997); RFC 4231 (test vectors).
    https://datatracker.ietf.org/doc/html/rfc2104
    https://datatracker.ietf.org/doc/html/rfc4231

    Parameters
    ----------
    key : bytes
        HMAC key (must be bytes, not str).
    data : bytes or str
        Data to authenticate. str is UTF-8 encoded.

    Returns
    -------
    str
        64-character lowercase hex string.

    Raises
    ------
    TypeError
        If key is not bytes, or data is not bytes or str.
    """
    if not isinstance(key, (bytes, bytearray)):
        raise TypeError(f"key must be bytes, got {type(key).__name__}")
    if isinstance(data, str):
        data = data.encode("utf-8")
    elif not isinstance(data, (bytes, bytearray)):
        raise TypeError(f"data must be bytes or str, got {type(data).__name__}")
    return _hmac.new(bytes(key), bytes(data), hashlib.sha256).hexdigest()
