"""Cryptographic primitives submodule (slimmed for mneme edu tree).

2026-08-16 教育边界裁剪：ed25519/merkle 子模块随本轮 vendor 裁剪删除——
mneme 实际只用 sha256_hash/hmac_sha256（omodul._decision_trail、
oprim.signature.compute 的决策轨迹指纹）。Ed25519 签名走
oprim.ed25519_sign（omodul.audit_record 延迟引用）。刷新 vendor 时
勿把 oprim/crypto/ed25519.py、merkle.py 整仓 dump 带回。
"""

from oprim.crypto.hashing import hmac_sha256, sha256_hash

__all__ = [
    "sha256_hash",
    "hmac_sha256",
]
