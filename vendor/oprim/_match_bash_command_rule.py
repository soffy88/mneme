"""Match a bash command string against an ordered list of BashRules."""
from __future__ import annotations

import fnmatch
from typing import Any


def match_bash_command_rule(cmd: str, *, rules: list[Any]) -> str:
    """Return the :data:`Decision` for *cmd* by matching against *rules*.

    Matching strategy (first rule that matches wins):

    1. Extract the first word of *cmd* and test it against ``rule.pattern``
       with :func:`fnmatch.fnmatch`.
    2. Also test the full *cmd* string against ``rule.pattern``.

    If no rule matches, returns ``"ask"``.

    Args:
        cmd: The bash command string to evaluate.
        rules: Ordered list of :class:`~oprim._hicode_types.BashRule` objects.

    Returns:
        A :data:`Decision` string: ``"allow"``, ``"deny"``, or ``"ask"``.

    Raises:
        ValueError: If *cmd* is empty.
    """
    if not cmd:
        raise ValueError("cmd must not be empty")

    first_word = cmd.split()[0] if cmd.split() else cmd

    for rule in rules:
        pattern = rule.pattern
        if fnmatch.fnmatch(first_word, pattern) or fnmatch.fnmatch(cmd, pattern):
            return str(rule.action)

    return "ask"
