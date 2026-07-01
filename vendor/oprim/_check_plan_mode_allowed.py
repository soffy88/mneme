"""P-NEW6 check_plan_mode_allowed — Plan Mode tool whitelist check."""
from __future__ import annotations

from oprim._hicode_types import ToolCall

_PLAN_ALLOWED: frozenset[str] = frozenset({
    "read", "grep", "glob", "list", "ls", "find",
    "cat", "head", "tail", "stat",
    "git_status", "git_log", "git_diff",
    "web_search", "web_fetch",
})

_PLAN_ALLOWED_PREFIXES: tuple[str, ...] = ("lsp_",)

_PLAN_BLOCKED: frozenset[str] = frozenset({
    "write", "edit", "multiedit", "patch",
    "bash", "run", "exec", "shell",
    "delete", "remove", "rm",
    "create_file", "write_file",
})


def check_plan_mode_allowed(tool_call: ToolCall, *, mode: str) -> bool:
    """Return True if *tool_call* is permitted under *mode*.

    Plan mode: only read-only tools allowed (conservative).
    Execute mode: all tools allowed.
    Unknown mode: conservative — deny write tools, allow known read tools.

    Args:
        tool_call: The tool call to evaluate.
        mode: "plan", "execute", or other string.

    Returns:
        True if the call is allowed, False if it should be blocked.
    """
    name = tool_call.name

    if mode == "execute":
        return True

    if mode == "plan":
        if name in _PLAN_ALLOWED:
            return True
        if any(name.startswith(pfx) for pfx in _PLAN_ALLOWED_PREFIXES):
            return True
        if name in _PLAN_BLOCKED:
            return False
        return False

    # Unknown mode: conservative
    if name in _PLAN_ALLOWED or any(name.startswith(p) for p in _PLAN_ALLOWED_PREFIXES):
        return True
    return False
