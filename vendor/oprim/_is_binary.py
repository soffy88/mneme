from __future__ import annotations


def is_binary(raw: bytes, *, sample_size: int = 8192) -> bool:
    """Return True if bytes look binary (NUL byte or >30% non-printable)."""
    if not raw:
        return False
    sample = raw[:sample_size]
    if b"\x00" in sample:
        return True
    non_printable = sum(1 for b in sample if b < 32 and b not in (9, 10, 13))
    return (non_printable / len(sample)) > 0.30
