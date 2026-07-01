from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from oskill._exceptions import OskillError


class IntegrityReport(BaseModel):
    valid: bool
    missing_refs: list[str]  # target_ids not in available_ids
    orphan_refs: list[str]  # available_ids not referenced by target_ids


def check_reference_integrity(
    *,
    ref_type: Literal["substrate_derivative", "concept_substrate", "note_ref"],
    source_id: str,
    target_ids: list[str],
    available_ids: set[str],
) -> IntegrityReport:
    """Check referential integrity for a single source → targets relationship.

    Internal oskill composition: pure set-operation algorithm (no oprim calls).

    Args:
        ref_type: Type of reference relationship
        source_id: ID of the source entity
        target_ids: IDs that source claims to reference
        available_ids: All IDs that actually exist

    Returns:
        IntegrityReport with missing_refs and orphan_refs

    Raises:
        OskillError: Unknown ref_type

    Example:
        >>> report = check_reference_integrity(
        ...     ref_type="note_ref",
        ...     source_id="note-1",
        ...     target_ids=["s1", "s2", "s99"],
        ...     available_ids={"s1", "s2"},
        ... )
        >>> report.missing_refs
        ['s99']
    """
    allowed = {"substrate_derivative", "concept_substrate", "note_ref"}
    if ref_type not in allowed:
        raise OskillError(f"Unknown ref_type: {ref_type!r}")

    target_set = set(target_ids)
    missing_refs = sorted(target_set - available_ids)
    orphan_refs = sorted(available_ids - target_set)

    return IntegrityReport(
        valid=len(missing_refs) == 0,
        missing_refs=missing_refs,
        orphan_refs=orphan_refs,
    )
