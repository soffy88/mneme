"""render_part — produce a human-readable string for a Part."""
from __future__ import annotations

from ._hicode_types import Part


def render_part(part: Part) -> str:
    """Return a string representation of *part*.

    Raises:
        ValueError: for unknown part types.
    """
    t = part.type

    if t == "text":
        return part.text or ""

    if t == "tool_call":
        tc = part.tool_call
        assert tc is not None
        args_summary = ", ".join(f"{k}={v!r}" for k, v in tc.args.items())
        return f"[tool_call: {tc.name}({args_summary})]"

    if t == "tool_result":
        tr = part.tool_result
        assert tr is not None
        return f"[tool_result: {tr.call_id[:8]}...]"

    if t == "file":
        return f"[file: {part.path}]"

    if t == "image":
        return "[image: <base64>]"

    if t == "reasoning":
        return f"<thinking>\n{part.text}\n</thinking>"

    raise ValueError(f"Unknown part type: {t!r}")
