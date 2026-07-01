"""Build a Question payload from raw inputs."""
from __future__ import annotations

from ._hicode_types import Question


def build_question_payload(*, header: str, text: str, options: list[str]) -> Question:
    """Construct a :class:`Question` with deduplicated options.

    Parameters
    ----------
    header:
        Optional heading / context shown above the question.
    text:
        The question body. Must be non-empty.
    options:
        Candidate answer strings. Duplicates are removed while preserving
        the first occurrence order.

    Raises
    ------
    ValueError
        If *text* is empty or whitespace-only.

    Returns
    -------
    Question
        Populated question ready for dispatch.
    """
    if not text:
        raise ValueError("text must not be empty")

    seen: set[str] = set()
    deduped: list[str] = []
    for opt in options:
        if opt not in seen:
            seen.add(opt)
            deduped.append(opt)

    return Question(text=text, options=deduped, header=header)
