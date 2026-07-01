# oprim/oprim/compute_dedup_key.py
from __future__ import annotations

import hashlib
from datetime import UTC, datetime


def compute_dedup_key(
    *,
    rule_id: str,
    entity_id: str,
    bucket_seconds: int = 3600,
    bucket_anchor: datetime | None = None,
) -> str:
    """Compute a time-bucket dedup key (SHA-256 hex, 64 chars).

    ⚠️ THIS IS NOT omodul fingerprint.
    omodul fingerprint = content identity (same input = same fp forever).
    compute_dedup_key = time-window identity (same input across different time
    buckets = different key).

    Args:
        rule_id: Rule/scenario ID (alert rule / cache namespace / rate-limit dimension).
        entity_id: Entity ID (hostname / user ID / endpoint / symbol).
        bucket_seconds: Time bucket size in seconds. Default 3600 (1 hour).
        bucket_anchor: Time to snap to bucket. None → datetime.now(UTC).

    Returns:
        SHA-256 hex digest (64 chars).

    Raises:
        ValueError: bucket_seconds <= 0 or naive bucket_anchor.
    """
    if bucket_seconds <= 0:
        raise ValueError(f"bucket_seconds must be > 0, got {bucket_seconds}")

    if bucket_anchor is None:
        bucket_anchor = datetime.now(UTC)

    if bucket_anchor.tzinfo is None:
        raise ValueError("bucket_anchor must be timezone-aware")

    timestamp = int(bucket_anchor.timestamp())
    bucket_start = (timestamp // bucket_seconds) * bucket_seconds

    composite = f"{rule_id}\x00{entity_id}\x00{bucket_start}\x00{bucket_seconds}"
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()
