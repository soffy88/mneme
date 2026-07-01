"""parts_to_message — assemble a Message from a list of Parts."""
from __future__ import annotations

from ._hicode_types import Message, Part

_VALID_ROLES = {"user", "assistant", "system", "tool"}


def parts_to_message(parts: list[Part], *, role: str) -> Message:
    """Return a Message with *role* and *parts*.

    Raises:
        ValueError: if *role* is not one of user / assistant / system / tool.
    """
    if role not in _VALID_ROLES:
        raise ValueError(
            f"role must be one of {sorted(_VALID_ROLES)!r}, got {role!r}"
        )
    return Message(role=role, parts=parts)
