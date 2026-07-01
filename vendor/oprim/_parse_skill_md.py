"""Parse a skill markdown file into a SkillSpec."""
from __future__ import annotations

import yaml

from oprim._hicode_types import SkillSpec


def parse_skill_md(content: str) -> SkillSpec:
    """Parse frontmatter YAML + body into a SkillSpec.

    The file must start with ``---``, contain a YAML block, and close with
    another ``---`` line.  Everything after the closing ``---`` is the body.

    Required frontmatter fields: ``name``, ``description``.
    Extra fields are silently ignored.

    Raises:
        ValueError: if the frontmatter is missing or ``name``/``description``
                    are absent.
    """
    if not content.startswith("---"):
        raise ValueError("skill markdown must begin with a YAML frontmatter block (---)")

    # Strip the leading ---
    rest = content[3:]
    if "\n---" not in rest:
        raise ValueError("skill markdown frontmatter block is not closed with ---")

    fm_raw, body = rest.split("\n---", 1)

    # Remove a single leading newline from body if present
    if body.startswith("\n"):
        body = body[1:]

    fm = yaml.safe_load(fm_raw) or {}

    name = fm.get("name")
    description = fm.get("description")

    if not name:
        raise ValueError("skill markdown frontmatter missing required field: name")
    if not description:
        raise ValueError("skill markdown frontmatter missing required field: description")

    return SkillSpec(name=str(name), description=str(description), body=body)
