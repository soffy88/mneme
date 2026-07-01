"""P-NEW8 restore_from_checkpoint — deserialize CheckpointData to RunState (pure, no IO).

The persistence chain is:
    make_checkpoint(serialize) -> obase.versionstore(write) -> ...
    ... -> obase.versionstore(read) -> restore_from_checkpoint(deserialize)

This oprim only handles the deserialization end. No file reads.
"""
from __future__ import annotations

from oprim._cc_types import CheckpointData, RunState

_SUPPORTED_VERSIONS = {"1"}


def restore_from_checkpoint(checkpoint: CheckpointData) -> RunState:
    """Restore a RunState from *checkpoint*.

    Args:
        checkpoint: CheckpointData previously created by make_checkpoint.

    Returns:
        Restored RunState.

    Raises:
        ValueError: If checkpoint is invalid, version is unsupported, or
                    required payload fields are missing.
    """
    if not checkpoint.session_id:
        raise ValueError("checkpoint.session_id is empty — invalid checkpoint")

    if checkpoint.version not in _SUPPORTED_VERSIONS:
        raise ValueError(
            f"Unsupported checkpoint version {checkpoint.version!r}. "
            f"Supported: {sorted(_SUPPORTED_VERSIONS)}"
        )

    payload = checkpoint.payload
    if not isinstance(payload, dict):
        raise ValueError("checkpoint.payload must be a dict")

    required = {"step", "data", "completed_steps", "state_session_id"}
    missing = required - set(payload.keys())
    if missing:
        raise ValueError(f"checkpoint.payload missing fields: {missing}")

    return RunState(
        session_id=str(payload["state_session_id"]),
        step=int(payload["step"]),
        data=dict(payload["data"]),
        completed_steps=list(payload["completed_steps"]),
    )
