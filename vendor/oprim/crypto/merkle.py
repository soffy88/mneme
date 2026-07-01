"""RFC 6962 Merkle Tree atomic operations."""

from __future__ import annotations

import hashlib


def rfc6962_merkle_root(leaves: list[bytes]) -> bytes:
    """RFC 6962 Merkle Tree Hash (MTH) root.

    Mathematical definition (RFC 6962 Section 2.1):
        MTH({}) = SHA-256("")
        MTH({d_0}) = SHA-256(0x00 || d_0)
        MTH(D[n]) = SHA-256(0x01 || MTH(D[0:k]) || MTH(D[k:n]))
            where k is the largest power of 2 less than n.

    Each leaf is arbitrary bytes (NOT pre-hashed). The function adds the
    0x00 domain-separation prefix before hashing.

    Returns 32-byte raw hash.

    Reference: RFC 6962 Section 2.1 (Certificate Transparency, 2013).
    https://datatracker.ietf.org/doc/html/rfc6962#section-2.1

    Parameters
    ----------
    leaves : list[bytes]
        Leaf data (arbitrary bytes each, not necessarily 32 bytes).

    Returns
    -------
    bytes
        32-byte Merkle root hash.

    Raises
    ------
    TypeError
        If leaves is not a list or contains non-bytes elements.
    """
    if not isinstance(leaves, list):
        raise TypeError(f"leaves must be list, got {type(leaves).__name__}")
    for i, leaf in enumerate(leaves):
        if not isinstance(leaf, (bytes, bytearray)):
            raise TypeError(f"leaf[{i}] must be bytes, got {type(leaf).__name__}")

    return _mth(leaves)


def _mth(leaves: list[bytes]) -> bytes:
    """Recursive MTH per RFC 6962 §2.1."""
    n = len(leaves)
    if n == 0:
        return hashlib.sha256(b"").digest()
    if n == 1:
        return hashlib.sha256(b"\x00" + bytes(leaves[0])).digest()
    k = 1
    while k * 2 < n:
        k *= 2
    return hashlib.sha256(b"\x01" + _mth(leaves[:k]) + _mth(leaves[k:])).digest()


def rfc6962_inclusion_proof(leaves: list[bytes], leaf_index: int) -> list[bytes]:
    """RFC 6962 Merkle Audit Path (inclusion proof) for a specific leaf.

    Mathematical definition (RFC 6962 Section 2.1.1):
        PATH(m, D[n]) returns the audit path needed to prove inclusion
        of leaf m in tree D[n].

    Returns list of sibling hashes from leaf-level to root-level (excluding root).
    Each sibling is 32 bytes.

    Reference: RFC 6962 Section 2.1.1.
    https://datatracker.ietf.org/doc/html/rfc6962#section-2.1.1

    Parameters
    ----------
    leaves : list[bytes]
        All leaf data (same format as rfc6962_merkle_root).
    leaf_index : int
        0-indexed position of the target leaf.

    Returns
    -------
    list[bytes]
        Audit path; each element is a 32-byte sibling hash.

    Raises
    ------
    ValueError
        If leaves is empty or leaf_index out of range [0, len(leaves)).
    TypeError
        If leaves contains non-bytes elements.
    """
    if not isinstance(leaves, list):
        raise TypeError(f"leaves must be list, got {type(leaves).__name__}")
    n = len(leaves)
    if n == 0:
        raise ValueError("leaves must not be empty")
    if not isinstance(leaf_index, int) or leaf_index < 0 or leaf_index >= n:
        raise ValueError(f"leaf_index {leaf_index!r} out of range [0, {n})")
    for i, leaf in enumerate(leaves):
        if not isinstance(leaf, (bytes, bytearray)):
            raise TypeError(f"leaf[{i}] must be bytes, got {type(leaf).__name__}")

    return _path(leaves, leaf_index)


def _path(leaves: list[bytes], m: int) -> list[bytes]:
    """RFC 6962 §2.1.1 PATH recursive construction."""
    n = len(leaves)
    if n == 1:
        return []
    k = 1
    while k * 2 < n:
        k *= 2
    if m < k:
        return _path(leaves[:k], m) + [_mth(leaves[k:])]
    else:
        return _path(leaves[k:], m - k) + [_mth(leaves[:k])]


def _verify_inclusion(
    leaf: bytes,
    leaf_index: int,
    n_leaves: int,
    proof: list[bytes],
    root: bytes,
) -> bool:
    """Verify a Merkle inclusion proof (used internally by tests)."""
    h = hashlib.sha256(b"\x00" + bytes(leaf)).digest()
    fn = leaf_index
    sn = n_leaves - 1
    for sibling in proof:
        if sn == 0:
            break  # pragma: no cover
        if fn % 2 == 1 or fn == sn:
            h = hashlib.sha256(b"\x01" + sibling + h).digest()
            while fn % 2 == 0 and fn != 0:
                fn >>= 1
                sn >>= 1
        else:
            h = hashlib.sha256(b"\x01" + h + sibling).digest()
        fn >>= 1
        sn >>= 1
    return h == root
