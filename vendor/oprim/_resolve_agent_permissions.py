"""Resolve a Persona's effective PermSet against a list of available tools."""
from __future__ import annotations

import fnmatch
from typing import Any

from oprim._hicode_types import Decision, PermSet, Persona

_PLAN_ALLOW = {"read", "grep", "glob"}
_PLAN_DENY = {"edit", "write", "bash"}


def resolve_agent_permissions(persona: Persona, *, all_tools: list[Any]) -> PermSet:
    """Compute the effective :class:`~oprim._hicode_types.PermSet` for *persona*.

    Resolution order:

    1. Set a default action for every tool based on ``persona.mode``:

       * ``"build"`` — every tool defaults to ``"allow"``.
       * ``"plan"``  — ``read``/``grep``/``glob`` default to ``"allow"``;
         ``edit``/``write``/``bash`` default to ``"deny"``; all others ``"ask"``.
       * Any other mode — all tools default to ``"ask"``.

    2. Apply ``persona.deny`` patterns: any tool whose name matches at least
       one deny pattern is set to ``"deny"``.

    3. Apply ``persona.allow`` patterns: any tool whose name matches at least
       one allow pattern is set to ``"allow"`` (overrides deny).

    Args:
        persona: The :class:`~oprim._hicode_types.Persona` to evaluate.
        all_tools: List of :class:`~oprim._hicode_types.Tool` objects representing
                   every tool available to the agent.

    Returns:
        A :class:`~oprim._hicode_types.PermSet` with ``tool_actions`` populated
        for every tool in *all_tools* and ``bash_rules`` taken from
        ``persona.bash_rules``.
    """
    tool_actions: dict[str, Decision] = {}

    # Step 1: defaults by mode
    for tool in all_tools:
        name = tool.name
        if persona.mode == "build":
            tool_actions[name] = "allow"
        elif persona.mode == "plan":
            if name in _PLAN_ALLOW:
                tool_actions[name] = "allow"
            elif name in _PLAN_DENY:
                tool_actions[name] = "deny"
            else:
                tool_actions[name] = "ask"
        else:
            tool_actions[name] = "ask"

    # Step 2: apply deny patterns
    for tool in all_tools:
        name = tool.name
        for pat in persona.deny:
            if fnmatch.fnmatch(name, pat):
                tool_actions[name] = "deny"
                break

    # Step 3: apply allow overrides
    for tool in all_tools:
        name = tool.name
        for pat in persona.allow:
            if fnmatch.fnmatch(name, pat):
                tool_actions[name] = "allow"
                break

    return PermSet(tool_actions=tool_actions, bash_rules=list(persona.bash_rules))
