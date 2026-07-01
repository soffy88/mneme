"""oprim.ed25519_sign — Ed25519 message signing."""
from __future__ import annotations


def ed25519_sign(message: bytes, *, private_key: bytes) -> bytes:
    """Sign *message* with an Ed25519 private key.

    Args:
        message: Arbitrary bytes to sign.
        private_key: 32-byte raw Ed25519 private key seed.

    Returns:
        64-byte Ed25519 signature.

    Raises:
        ValueError: If *private_key* is not 32 bytes.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: PLC0415

    if len(private_key) != 32:
        raise ValueError(f"private_key must be 32 bytes, got {len(private_key)}")

    key = Ed25519PrivateKey.from_private_bytes(private_key)
    return key.sign(message)
