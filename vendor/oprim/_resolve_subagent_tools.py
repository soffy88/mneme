"""Resolve the tool list for a subagent given a Persona."""
from __future__ import annotations

import fnmatch
from typing import Any

from ._hicode_types import Persona, Tool


def resolve_subagent_tools(persona: Persona, *, all_tools: list[Any]) -> list[Any]:
    """Return the filtered list of :class:`Tool` objects for *persona*.

    Rules applied in order:

    1. Remove the tool named ``"task"`` (prevents infinite recursion).
    2. If ``persona.allow`` is non-empty, keep only tools whose name matches
       at least one allow pattern (glob-style).
    3. Remove tools whose name matches any pattern in ``persona.deny``.

    Parameters
    ----------
    persona:
        Persona whose ``allow``/``deny`` lists drive filtering.
    all_tools:
        Full ``list[Tool]`` to filter.

    Returns
    -------
    list[Tool]
        Filtered tool list preserving input order.
    """
    tools: list[Tool] = [t for t in all_tools if t.name != "task"]

    if persona.allow:
        tools = [
            t for t in tools
            if any(fnmatch.fnmatch(t.name, pat) for pat in persona.allow)
        ]

    if persona.deny:
        tools = [
            t for t in tools
            if not any(fnmatch.fnmatch(t.name, pat) for pat in persona.deny)
        ]

    return tools
