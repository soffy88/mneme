"""make_tool_call_part — construct a tool_call Part."""
from __future__ import annotations

from ._hicode_types import Part, ToolCall


def make_tool_call_part(*, call: ToolCall) -> Part:
    """Return a Part of type 'tool_call' wrapping *call*."""
    return Part(type="tool_call", tool_call=call)
