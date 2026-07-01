from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class EventType(str, Enum):
    SUBSTRATE_CREATED = "substrate_created"
    SUBSTRATE_UPDATED = "substrate_updated"
    SUBSTRATE_DELETED = "substrate_deleted"
    SUBSTRATE_PINNED = "substrate_pinned"
    SUBSTRATE_UNPINNED = "substrate_unpinned"
    DERIVATIVE_CREATED = "derivative_created"
    DERIVATIVE_DELETED = "derivative_deleted"
    NOTE_CREATED = "note_created"
    NOTE_UPDATED = "note_updated"
    NOTE_DELETED = "note_deleted"
    CONCEPT_CREATED = "concept_created"
    CONCEPT_LINKED = "concept_linked"
    CONCEPT_UNLINKED = "concept_unlinked"
    # Legacy/Others
    SUBSTRATE_UPSERT = "substrate_upsert"
    SUBSTRATE_DELETE = "substrate_delete"

@dataclass
class ChangefeedEvent:
    id: str
    user_id: str
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    aggregate_id: str | None = None
    sequence: int = 0
    created_at: float = 0.0

    @classmethod
    def from_dict(cls, data: dict) -> ChangefeedEvent:
        return cls(
            id=data.get("id", ""),
            user_id=data.get("user_id", ""),
            type=EventType(data.get("type", "substrate_created")),
            payload=data.get("payload", {}),
            aggregate_id=data.get("aggregate_id"),
            sequence=data.get("sequence", 0),
            created_at=data.get("created_at", 0.0),
        )
