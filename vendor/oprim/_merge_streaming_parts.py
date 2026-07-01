"""merge_streaming_parts — collapse a list of PartDeltas into a single Part."""
from __future__ import annotations

import json

from ._hicode_types import Part, PartDelta, ToolCall


def merge_streaming_parts(deltas: list[PartDelta]) -> Part:
    """Merge streaming *deltas* into one complete Part.

    Raises:
        ValueError: if *deltas* is empty, or if a tool_call part ends with
                    incomplete / invalid JSON args.
    """
    if not deltas:
        raise ValueError("deltas must not be empty")

    first = deltas[0]
    kind = first.type

    if kind == "text":
        combined = "".join(d.text or "" for d in deltas)
        return Part(type="text", text=combined)

    if kind == "tool_call":
        args_json = "".join(d.args_chunk or "" for d in deltas)
        try:
            parsed_args = json.loads(args_json)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Incomplete or invalid JSON in tool_call args: {exc}"
            ) from exc
        tool_call = ToolCall(
            id=first.tool_call_id or "",
            name=first.tool_name or "",
            args=parsed_args,
        )
        return Part(type="tool_call", tool_call=tool_call)

    raise ValueError(f"Unsupported delta type for merging: {kind!r}")
