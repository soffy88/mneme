"""oprim.video_element_edit — Edit elements within video metadata/transcript."""
from __future__ import annotations

from enum import Enum
from typing import Any


class VideoEditOperation(str, Enum):
    REPLACE = "replace"
    INSERT = "insert"
    DELETE = "delete"


async def video_element_edit(
    *,
    elements: list[dict],
    operation: str,
    target_index: int,
    replacement: dict | None = None,
    caller: Any,
) -> list[dict]:
    """Edit an element in a video metadata/transcript list.

    Args:
        elements: List of element dicts to operate on.
        operation: One of "replace", "insert", "delete".
        target_index: Index into elements for replace/delete; insertion point for insert.
        replacement: New element dict for replace/insert operations.
        caller: LLM caller (reserved for future enrichment; not called here).

    Returns:
        New list with the edit applied.

    Raises:
        ValueError: If operation is "replace" or "insert" and replacement is None/empty.
        IndexError: If target_index is out of range for replace or delete.
    """
    op = operation.lower()

    if op == VideoEditOperation.REPLACE:
        if not replacement:
            raise ValueError(
                "video_element_edit: replacement must be provided for 'replace' operation"
            )
        if target_index < 0 or target_index >= len(elements):
            raise IndexError(
                f"video_element_edit: target_index {target_index} out of range "
                f"(list length {len(elements)})"
            )
        result = list(elements)
        result[target_index] = replacement
        return result

    if op == VideoEditOperation.INSERT:
        if not replacement:
            raise ValueError(
                "video_element_edit: replacement must be provided for 'insert' operation"
            )
        result = list(elements)
        result.insert(target_index, replacement)
        return result

    if op == VideoEditOperation.DELETE:
        if target_index < 0 or target_index >= len(elements):
            raise IndexError(
                f"video_element_edit: target_index {target_index} out of range "
                f"(list length {len(elements)})"
            )
        result = list(elements)
        del result[target_index]
        return result

    raise ValueError(f"video_element_edit: unknown operation '{operation}'")
