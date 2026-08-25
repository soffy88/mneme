"""Compatibility export for the canonical Mneme Tutor answer policy.

The policy lives in ``mneme_core`` so the API, agent and education runtime do
not grow subtly different answer-tier rules.  This module preserves the
historical ``oprim.answer_policy`` import used by existing services/tests.
"""

from mneme_core.tutor_control import (
    FULL_EXAMPLE,
    HINT_LADDER,
    NEVER,
    OWN_HOMEWORK,
    STUCK,
    SYSTEM_TAUGHT,
    WRITING,
    answer_policy,
)

__all__ = [
    "answer_policy",
    "OWN_HOMEWORK",
    "WRITING",
    "SYSTEM_TAUGHT",
    "STUCK",
    "NEVER",
    "FULL_EXAMPLE",
    "HINT_LADDER",
]
