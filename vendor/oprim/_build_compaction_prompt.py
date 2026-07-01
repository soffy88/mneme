"""Build the LLM prompt used to summarise a compaction window."""
from __future__ import annotations

from typing import Any

from ._hicode_types import Window

_SYSTEM_INSTRUCTION = (
    "Summarize the following conversation concisely. "
    "Preserve all important facts, decisions, and context. "
    "Write in third person and use past tense."
)


def _serialize_window(window: Window) -> str:
    """Render the to_compact messages as plain text for the user turn."""
    lines: list[str] = []
    for msg in window.to_compact:
        role_label = msg.role.upper()
        part_texts: list[str] = []
        for part in msg.parts:
            if part.type == "text" and part.text:
                part_texts.append(part.text)
            elif part.type == "tool_call" and part.tool_call is not None:
                tc = part.tool_call
                part_texts.append(f"[tool_call name={tc.name!r} args={tc.args!r}]")
            elif part.type == "tool_result" and part.tool_result is not None:
                tr = part.tool_result
                part_texts.append(
                    f"[tool_result call_id={tr.call_id!r} content={tr.content!r}"
                    f"{' ERROR' if tr.is_error else ''}]"
                )
            elif part.type in ("file", "image"):
                path_str = str(part.path) if part.path else "<unknown>"
                part_texts.append(f"[{part.type} path={path_str!r}]")
            else:
                # Fallback: emit whatever text is available.
                if part.text:
                    part_texts.append(part.text)
        lines.append(f"{role_label}: " + " ".join(part_texts))
    return "\n".join(lines)


def build_compaction_prompt(window: Window) -> list[dict[str, Any]]:
    """Return an LLM message list that asks the model to summarise window.to_compact.

    Args:
        window: A Window whose to_compact list must be non-empty.

    Returns:
        A list of dicts with "role" and "content" keys suitable for passing
        directly to a chat-completion API.

    Raises:
        ValueError: If window.to_compact is empty.
    """
    if not window.to_compact:
        raise ValueError("window.to_compact must not be empty")

    serialized = _serialize_window(window)

    return [
        {"role": "system", "content": _SYSTEM_INSTRUCTION},
        {"role": "user", "content": serialized},
    ]
