"""P-NEW2 interpolate_skill_args — replace skill template variables.

Placeholders:
    $ARGUMENTS   — all positional args joined by space
    $0, $1, ...  — individual positional args by index
    ${NAME}      — named arg (must be in args dict as "NAME")
"""
from __future__ import annotations

import re


def interpolate_skill_args(skill_body: str, *, args: dict[str, str]) -> str:
    """Replace $ARGUMENTS / $N / ${NAME} placeholders in *skill_body*.

    Args:
        skill_body: Skill template text.
        args: str->str map. Numeric keys ("0","1",...) are positional.

    Returns:
        Interpolated string.

    Raises:
        ValueError: If a referenced key is missing from *args*.
    """
    result = skill_body

    # $ARGUMENTS -> join all positional args in sorted-index order
    if "$ARGUMENTS" in result:
        positional = [args[k] for k in sorted(args) if k.isdigit()]
        result = result.replace("$ARGUMENTS", " ".join(positional))

    # ${NAME} named placeholders
    def _named(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in args:
            raise ValueError(f"Missing skill arg: {name!r}")
        return args[name]

    result = re.sub(r"\$\{([^}]+)\}", _named, result)

    # $N positional (after ${} so we don't clobber brace form)
    def _positional(m: re.Match[str]) -> str:
        idx = m.group(1)
        if idx not in args:
            raise ValueError(f"Missing positional arg: ${idx}")
        return args[idx]

    result = re.sub(r"\$(\d+)", _positional, result)

    return result
