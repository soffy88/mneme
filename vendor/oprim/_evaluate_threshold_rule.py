from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ALLOWED_OPERATORS = {">=", ">", "<", "<="}


class ThresholdResult(BaseModel):
    triggered: bool  # severity != "ok"
    severity: Literal["ok", "warn", "critical"]
    reason: str  # human-readable, e.g. "cpu_usage=85.0 >= warn=70.0"
    metric: str  # from rule_spec["metric"]
    current_value: float
    threshold_breached: float | None  # the warn/critical threshold that was hit, or None


class ThresholdRuleError(Exception):
    """rule_spec configuration error."""


def evaluate_threshold_rule(
    *,
    current_value: float,
    rule_spec: dict,  # type: ignore[type-arg]
) -> ThresholdResult:
    """Single-value vs dual-threshold triple-tier evaluation (for alert engines).

    Operators >= and > : higher values are more severe (e.g. CPU usage)
    Operators <= and < : lower values are more severe (e.g. balance, health score)

    Raises ThresholdRuleError immediately on any misconfiguration (missing fields,
    bad operator, inverted thresholds) — silent pass = missed alert = hard bug.
    """
    for required in ("metric", "operator", "threshold"):
        if required not in rule_spec:
            raise ThresholdRuleError(f"rule_spec missing required field: {required}")

    metric = rule_spec["metric"]
    operator = rule_spec["operator"]
    threshold = rule_spec["threshold"]

    if operator not in ALLOWED_OPERATORS:
        raise ThresholdRuleError(
            f"unsupported operator: {operator!r}, allowed: {sorted(ALLOWED_OPERATORS)}"
        )

    if not isinstance(threshold, dict):
        raise ThresholdRuleError(f"threshold must be dict, got {type(threshold).__name__}")

    if "warn" not in threshold or "critical" not in threshold:
        raise ThresholdRuleError("threshold missing 'warn' or 'critical' field")

    warn = float(threshold["warn"])
    critical = float(threshold["critical"])

    if operator in (">=", ">"):
        if warn >= critical:
            raise ThresholdRuleError(
                f"for operator {operator!r}, warn ({warn}) must be < critical ({critical})"
            )
    else:  # "<=" / "<"
        if warn <= critical:
            raise ThresholdRuleError(
                f"for operator {operator!r}, warn ({warn}) must be > critical ({critical})"
            )

    def _cmp(left: float, right: float, op: str) -> bool:
        if op == ">=":
            return left >= right
        if op == ">":
            return left > right
        if op == "<=":
            return left <= right
        return left < right  # op == "<"

    severity: Literal["ok", "warn", "critical"]
    breached: float | None

    if _cmp(current_value, critical, operator):
        severity = "critical"
        breached = critical
    elif _cmp(current_value, warn, operator):
        severity = "warn"
        breached = warn
    else:
        severity = "ok"
        breached = None

    if breached is not None:
        reason = f"{metric}={current_value} {operator} {severity}={breached}"
    else:
        reason = f"{metric}={current_value} within thresholds (ok)"

    return ThresholdResult(
        triggered=(severity != "ok"),
        severity=severity,
        reason=reason,
        metric=metric,
        current_value=current_value,
        threshold_breached=breached,
    )
