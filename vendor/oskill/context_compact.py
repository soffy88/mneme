"""K-06 context_compact — LLM-driven conversation history compaction.

Composes oprim:
    - should_compact
    - select_compaction_window
    - extract_pinned_messages
    - build_compaction_prompt
    - merge_summary
    - (LLMCaller Protocol injection for summarisation)

IO-orchestration (LLM call). Not used as sub-call by sibling oskills.
"""
from __future__ import annotations

from typing import Any, List, Protocol, cast

from oprim import (
    build_compaction_prompt,
    extract_pinned_messages,  # noqa: F401
    merge_summary,
    select_compaction_window,
    should_compact,
)
from oprim._hicode_types import Message


class LLMCaller(Protocol):
    async def __call__(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]: ...


async def context_compact(
    history: list[Message],
    *,
    caller: LLMCaller,
    budget_tokens: int,
) -> list[Message]:
    """Compact conversation history when it exceeds token budget.

    Composes: should_compact, select_compaction_window, extract_pinned_messages,
              build_compaction_prompt, merge_summary, caller (LLM injection).

    Args:
        history: Full conversation history.
        caller: LLM caller Protocol for summarisation.
        budget_tokens: Token budget threshold.

    Returns:
        Compacted history (original if no compaction needed).
    """
    if not should_compact(history, budget_tokens=budget_tokens, model=""):
        return history

    window = select_compaction_window(history)

    if not window.to_compact:
        return history

    prompt_msgs = build_compaction_prompt(window)
    response = await caller(messages=prompt_msgs, max_tokens=1024)

    # Extract summary text from response
    summary = ""
    content = response.get("content", "")
    if isinstance(content, str):
        summary = content
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                summary = block.get("text", "")
                break

    return cast(List[Message], merge_summary(summary, tail=window.to_keep))
