"""Shared return types for AII RFC functions.

Shared across oprim (P-AII-*) and oskill (K-AII-*).
All types are frozen dataclasses to guarantee deterministic equality.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FailureLessonResult:
    lesson: str
    trigger_type: str
    evidence: dict
    subject_ref: str | None = None


@dataclass
class ClusterResult:
    clusters: list[dict]  # [{representative: str, members: list[str], size: int}]


@dataclass
class GapReport:
    high_miss_topics: list[dict]   # [{topic: str, miss_count: int}]
    stale_unverified: list[str]    # ku_id list
    isolated_kus: list[str]        # ku_ids with graph degree == 0
    grade_imbalance: dict          # {domain: {grade: count}}
