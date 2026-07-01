"""Classify the risk level of a tool call."""
from __future__ import annotations

from oprim._hicode_types import ToolCall

_LOW_TOOLS = {"read", "grep", "glob", "list", "ls"}
_MEDIUM_TOOLS = {"edit", "write", "multiedit", "patch"}
_HIGH_BASH_TOKENS = {"rm", "sudo", "chmod", "chown", "dd", "mkfs", "format"}


def classify_risk(call: ToolCall) -> str:
    """Return the :data:`RiskLevel` for *call*.

    Rules (in priority order):

    * ``read``, ``grep``, ``glob``, ``list``, ``ls`` → ``"low"``
    * ``edit``, ``write``, ``multiedit``, ``patch`` → ``"medium"``
    * ``bash``:

      * command contains any of ``rm sudo chmod chown dd mkfs format`` → ``"high"``
      * otherwise → ``"medium"``

    * Any other tool → ``"medium"``

    Args:
        call: The tool call to classify.

    Returns:
        A :data:`RiskLevel` string (``"low"``, ``"medium"``, or ``"high"``).
    """
    name = call.name

    if name in _LOW_TOOLS:
        return "low"

    if name in _MEDIUM_TOOLS:
        return "medium"

    if name == "bash":
        cmd = call.args.get("command", "")
        tokens = set(cmd.split())
        if tokens & _HIGH_BASH_TOKENS:
            return "high"
        return "medium"

    return "medium"
