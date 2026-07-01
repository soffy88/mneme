"""Cryptographic primitives submodule."""

from oprim.crypto.ed25519 import (
    ed25519_keypair_generate,
    ed25519_sign,
    ed25519_verify,
    generate_keypair,
    load_private_key_pem,
    load_public_key_pem,
    save_keypair_pem,
    sign,
    verify,
)
from oprim.crypto.hashing import hmac_sha256, sha256_hash
from oprim.crypto.merkle import rfc6962_inclusion_proof, rfc6962_merkle_root

__all__ = [
    "sha256_hash",
    "hmac_sha256",
    "rfc6962_merkle_root",
    "rfc6962_inclusion_proof",
    "ed25519_keypair_generate",
    "ed25519_sign",
    "ed25519_verify",
    "generate_keypair",
    "sign",
    "verify",
    "save_keypair_pem",
    "load_private_key_pem",
    "load_public_key_pem",
]
