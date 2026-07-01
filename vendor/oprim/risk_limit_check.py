"""oprim.risk_limit_check — Evaluate position / drawdown / rule-based risk limits."""
from __future__ import annotations

from typing import Any


def risk_limit_check(
    position_value: float,
    *,
    max_position: float,
    max_drawdown: float | None = None,
    current_drawdown: float | None = None,
    rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check position and optional drawdown/rule limits.

    Args:
        position_value: Current absolute position value (e.g. USD notional).
        max_position: Hard limit on absolute position value.
        max_drawdown: Maximum allowed drawdown fraction (0–1), e.g. 0.10 for 10%.
            Required when *current_drawdown* is provided.
        current_drawdown: Current drawdown fraction (positive = loss).
        rules: Optional list of custom rule dicts, each with:
            - ``"name"`` (str): Rule identifier.
            - ``"limit"`` (float): Threshold.
            - ``"value"`` (float): Observed value.
            - ``"direction"`` (str): ``"above"`` (fail if value > limit) or
              ``"below"`` (fail if value < limit).

    Returns:
        Dict with keys:

        - ``pass`` (bool) – True when all limits are satisfied.
        - ``violated_rule`` (str | None) – Name of the first violated rule,
          or None if all pass.

    Raises:
        ValueError: If *max_position* ≤ 0 or drawdown args are inconsistent.
    """
    if max_position <= 0:
        raise ValueError(f"max_position must be > 0, got {max_position}")

    # 1. Position limit
    if abs(position_value) > max_position:
        return {"pass": False, "violated_rule": "max_position"}

    # 2. Drawdown limit
    if current_drawdown is not None:
        if max_drawdown is None:
            raise ValueError("max_drawdown must be provided when current_drawdown is given")
        if max_drawdown < 0 or max_drawdown > 1:
            raise ValueError(f"max_drawdown must be in [0, 1], got {max_drawdown}")
        if current_drawdown > max_drawdown:
            return {"pass": False, "violated_rule": "max_drawdown"}

    # 3. Custom rules
    for rule in rules or []:
        name = rule.get("name", "unnamed_rule")
        limit = float(rule["limit"])
        value = float(rule["value"])
        direction = rule.get("direction", "above")
        if direction == "above" and value > limit:
            return {"pass": False, "violated_rule": name}
        if direction == "below" and value < limit:
            return {"pass": False, "violated_rule": name}

    return {"pass": True, "violated_rule": None}
