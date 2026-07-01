"""P-NEW7 make_checkpoint — serialize RunState to CheckpointData (pure, no IO).

The persistence chain is:
    make_checkpoint(serialize) -> obase.versionstore(write disk) -> ...
    ... -> obase.versionstore(read disk) -> restore_from_checkpoint(deserialize)

This oprim only handles the serialization end. No file writes.
"""
from __future__ import annotations

import datetime
import json

from oprim._cc_types import CheckpointData, RunState


def make_checkpoint(state: RunState, *, session_id: str) -> CheckpointData:
    """Serialize *state* to a CheckpointData structure.

    Args:
        state: Current run state to checkpoint.
        session_id: Session identifier (must be non-empty).

    Returns:
        CheckpointData ready for persistence (no IO performed here).

    Raises:
        ValueError: If session_id is empty or state data is not JSON-serializable.
    """
    if not session_id:
        raise ValueError("session_id must not be empty")

    payload = {
        "step": state.step,
        "data": state.data,
        "completed_steps": state.completed_steps,
        "state_session_id": state.session_id,
    }

    try:
        json.dumps(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"RunState contains non-serializable data: {exc}") from exc

    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    return CheckpointData(
        session_id=session_id,
        timestamp=timestamp,
        version="1",
        payload=payload,
    )
