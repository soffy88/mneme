"""Parse a raw dict into an Answer dataclass."""
from __future__ import annotations

from typing import Any

from ._hicode_types import Answer


def parse_question_answer(raw: dict[str, Any]) -> Answer:
    """Wrap a raw answer dict in an :class:`Answer` instance.

    *raw* must contain at least one of ``"option_idx"`` (int) or
    ``"text"`` (str) with a non-``None`` value.

    Parameters
    ----------
    raw:
        Mapping produced by the question-answer layer.  Expected keys:

        * ``"option_idx"`` – zero-based index into the question's options list
          (optional).
        * ``"text"`` – free-text answer (optional).

    Raises
    ------
    ValueError
        If neither ``"option_idx"`` nor ``"text"`` is present, or both are
        ``None``.

    Returns
    -------
    Answer
        Populated answer; index bounds are *not* validated here (the options
        list is unavailable at this layer).
    """
    option_idx = raw.get("option_idx")
    text = raw.get("text")

    if option_idx is None and text is None:
        raise ValueError(
            "raw answer must contain at least one of 'option_idx' or 'text'"
        )

    return Answer(option_idx=option_idx, text=text)
