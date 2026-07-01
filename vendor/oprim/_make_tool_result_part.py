"""make_tool_result_part — construct a tool_result Part."""
from __future__ import annotations

from ._hicode_types import Part, ToolResult


def make_tool_result_part(*, result: ToolResult) -> Part:
    """Return a Part of type 'tool_result' wrapping *result*."""
    return Part(type="tool_result", tool_result=result)
