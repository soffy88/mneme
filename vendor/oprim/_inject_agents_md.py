"""Inject AGENTS.md content into a system prompt."""
from __future__ import annotations

_ANCHOR = "# AGENTS"
_HEADER = "\n\n## Project Agents\n"


def inject_agents_md(prompt: str, *, agents_md: str) -> str:
    """Inject *agents_md* content into *prompt*.

    If *agents_md* is empty the prompt is returned unchanged.

    If the string ``"# AGENTS"`` is present in *prompt*, the agents content
    is inserted immediately after that anchor line.  Otherwise it is appended
    at the end of the prompt.

    The injected block is wrapped with the ``## Project Agents`` header.

    Parameters
    ----------
    prompt:
        Existing system prompt text.
    agents_md:
        Content to inject.  Returning *prompt* unchanged when falsy/empty.

    Returns
    -------
    str
        Updated prompt with agents content injected.
    """
    if not agents_md or not agents_md.strip():
        return prompt

    block = _HEADER + agents_md

    if _ANCHOR in prompt:
        idx = prompt.index(_ANCHOR)
        # Find end of the anchor line
        newline_pos = prompt.find("\n", idx)
        if newline_pos == -1:
            # Anchor is at the very end of the string with no newline
            return prompt + block
        return prompt[: newline_pos] + block + prompt[newline_pos:]

    return prompt + block
