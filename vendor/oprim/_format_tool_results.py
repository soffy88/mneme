"""Convert ToolResult objects into tool_result Part objects."""
from __future__ import annotations

from ._hicode_types import Part, ToolResult

_MAX_CONTENT_LENGTH = 10_000
_TRUNCATION_SUFFIX = "[... truncated ...]"


def format_tool_results(results: list[ToolResult]) -> list[Part]:
    """Convert a list of ToolResult objects into tool_result Part objects.

    Content longer than 10 000 characters is truncated and the suffix
    ``"[... truncated ...]"`` is appended.

    Parameters
    ----------
    results:
        List of ToolResult instances to convert.

    Returns
    -------
    list[Part]
        Corresponding list of Part objects with ``type="tool_result"``.
        Returns an empty list when *results* is empty.
    """
    if not results:
        return []

    parts: list[Part] = []
    for r in results:
        content = r.content
        if len(content) > _MAX_CONTENT_LENGTH:
            content = content[:_MAX_CONTENT_LENGTH] + _TRUNCATION_SUFFIX
        truncated_result = ToolResult(
            call_id=r.call_id,
            content=content,
            is_error=r.is_error,
        )
        parts.append(Part(type="tool_result", tool_result=truncated_result))
    return parts
