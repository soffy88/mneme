"""P-NEW1 match_skill_trigger — match task input to an auto-trigger SkillSpec."""
from __future__ import annotations

import re

from oprim._hicode_types import SkillSpec


def _skill_priority(skill: SkillSpec) -> int:
    return len(skill.description or "")


def match_skill_trigger(task_input: str, *, skills: list[SkillSpec]) -> SkillSpec | None:
    """Return the first SkillSpec whose trigger matches *task_input*, or None.

    Matching rules (first-match after priority sort wins):
    1. The skill's name appears verbatim in task_input (case-insensitive).
    2. Any keyword in skill.description (comma/space split) appears in task_input.

    Skills with longer descriptions are checked first (higher specificity).

    Args:
        task_input: User input / task description string.
        skills: List of SkillSpec to check.

    Returns:
        First matching SkillSpec, or None if no match.
    """
    if not task_input or not skills:
        return None

    lower_input = task_input.lower()
    sorted_skills = sorted(skills, key=_skill_priority, reverse=True)

    for skill in sorted_skills:
        if skill.name.lower() in lower_input:
            return skill
        if skill.description:
            keywords = re.split(r"[,\s]+", skill.description.lower())
            if any(kw and kw in lower_input for kw in keywords):
                return skill

    return None
