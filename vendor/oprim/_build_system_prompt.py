"""Build a formatted system prompt from agent instructions, project context, and tools."""
from __future__ import annotations

from typing import Any


def build_system_prompt(*, agent: str, project_ctx: str, tools: list[dict[str, Any]]) -> str:
    """Assemble a system prompt string.

    Parameters
    ----------
    agent:
        Core agent instruction text.  Must be non-empty.
    project_ctx:
        Optional project-level context.  Omitted when empty.
    tools:
        List of dicts with ``"name"`` and ``"description"`` keys describing
        available tools.  Omitted when empty.

    Returns
    -------
    str
        Formatted system prompt.

    Raises
    ------
    ValueError
        If *agent* is empty or whitespace-only.
    """
    if not agent or not agent.strip():
        raise ValueError("agent instructions must not be empty")

    parts: list[str] = [agent.strip()]

    if project_ctx and project_ctx.strip():
        parts.append("## Project Context\n" + project_ctx.strip())

    if tools:
        lines = ["## Available Tools"]
        for tool in tools:
            name = tool.get("name", "")
            description = tool.get("description", "")
            lines.append(f"- **{name}**: {description}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)
