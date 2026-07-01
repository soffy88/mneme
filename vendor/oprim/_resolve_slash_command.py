"""P-NEW3 resolve_slash_command — map /command input to a registered SkillRef."""
from __future__ import annotations

from typing import Any

from oprim._cc_types import SkillRef


def resolve_slash_command(
    input: str,
    *,
    registry: dict[str, Any],
) -> SkillRef | None:
    """Parse a slash command from *input* and look it up in *registry*.

    Contract:
        - Non-slash (not starting with /) -> None
        - "/" with nothing after -> None
        - Unregistered command -> None
        - Registered: return SkillRef(name, args=remaining tokens)

    Args:
        input: Raw user input, e.g. "/deploy --env prod".
        registry: Map of command_name -> registered value.

    Returns:
        SkillRef with name and parsed args, or None.
    """
    stripped = input.strip()
    if not stripped.startswith("/"):
        return None

    rest = stripped[1:]
    if not rest or rest.startswith(" "):
        return None

    tokens = rest.split()
    if not tokens:
        return None

    cmd_name = tokens[0]
    if not cmd_name:
        return None

    if cmd_name not in registry:
        return None

    return SkillRef(
        name=cmd_name,
        args=tokens[1:],
        raw_input=stripped,
    )
