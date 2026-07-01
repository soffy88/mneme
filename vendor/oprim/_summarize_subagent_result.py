"""Summarize a SubagentResult into a plain string."""
from __future__ import annotations

from ._hicode_types import SubagentResult

_TRUNCATION_SUFFIX = "... [truncated]"


def summarize_subagent_result(result: SubagentResult, *, max_len: int = 2000) -> str:
    """Return a human-readable summary of *result*.

    Behaviour:

    * Empty ``content`` returns ``"(no result)"``.
    * ``content`` longer than *max_len* is truncated with
      ``"... [truncated]"`` appended (the suffix fits within *max_len*).
    * When ``result.status == "error"``, the summary is prefixed with
      ``"ERROR: {result.error or 'unknown'}\\n"``.

    Parameters
    ----------
    result:
        The subagent result to summarise.
    max_len:
        Maximum character length of the *content* portion of the output
        (before any error prefix).
    """
    content = result.content

    if not content:
        summary = "(no result)"
    elif len(content) > max_len:
        keep = max_len - len(_TRUNCATION_SUFFIX)
        summary = content[:keep] + _TRUNCATION_SUFFIX
    else:
        summary = content

    if result.status == "error":
        error_label = result.error or "unknown"
        summary = f"ERROR: {error_label}\n{summary}"

    return summary
