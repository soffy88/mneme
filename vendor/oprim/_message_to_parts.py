"""message_to_parts — extract the list of Parts from a Message."""
from __future__ import annotations

from ._hicode_types import Message, Part


def message_to_parts(message: Message) -> list[Part]:
    """Return the parts list contained in *message*."""
    return message.parts
