"""Learner-side evidence contracts (byoungd/up G1-G4, clean rewrite).

Method and field structures adapted from byoungd/up, "Life Level-Up Guide"
(``https://github.com/byoungd/up``), by byoungd and contributors, licensed
CC BY-NC 4.0 (content). Source pages: ``docs/templates/evidence-chain.md``,
``docs/templates/ai-learning-log.md``, ``docs/templates/ai-task-brief.md``,
``docs/templates/ai-evaluation.md`` and
``docs/reference/sources-and-citation.md`` (v1.1.0, 2026-11-23).

This is a clean rewrite for Mneme's K12 learner: only field structures and
methods were borrowed, reworded for students and turned into fail-closed
pure-function gates. No book prose, no English content and no personal
narrative was copied. Mneme is non-commercial, which is compatible with
CC BY-NC 4.0; commercial use would need a separate licence from the author.

What each contract is, and what it is not:

- G1 evidence chain: a LEARNER-performance gate (one question, four time
  points). It is not the Tongjiang fact table (textbook facts) and not the
  physics G1 content-admission gate; the three share the fact /
  explanation / hypothesis vocabulary but gate different objects.
- G2 AI-learning log: the learner-side complement to physics G1. It
  decides what AI helped with versus what was outsourced; an AI-assisted
  score must never be written into mastery.
- G3 task brief + evaluation record: "fix the eval set before running,
  then run, then cost everything, then decide adopt / fix / stop".
- G4 source freshness: the time dimension missing from the G1 source
  ledger and citation_check (which only check that a source exists and
  parses). It does not duplicate citation_check.

Pure functions: no DB, no network, no LLM. Mastery thresholds stay
single-sourced in services.learner_model (GATE / MASTERED); this module
never redefines them -- G2 only names which sources may back a mastery
write (direct_accuracy, bkt, fsrs).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Mapping, Optional

# ── shared vocabulary ─────────────────────────────────────────────────────

TRANSFER_CONDITIONS = frozenset(
    {
        "topic",
        "audience",
        "time_limit",
        "material",
        "tool_permission",
        "task_purpose",
        "modality",
    }
)
"""Conditions a transfer / parallel task may change (one at a time)."""

EVAL_CASE_KINDS = frozenset(
    {"normal", "boundary", "missing", "conflict", "desensitised_historical"}
)
"""An eval set must hold at least one case of every kind."""

SENSITIVITY_LEVELS = frozenset({"public", "internal", "confidential", "restricted"})

REQUIRED_HUMAN_GATES = frozenset(
    {
        "source",
        "fact",
        "privacy",
        "quality",
        "cost",
        "tool_authorisation",
        "responsibility",
    }
)

EVAL_DECISIONS = frozenset({"adopt", "keep_status_quo", "fix_and_retest", "stop"})

CHAIN_DECISIONS = frozenset(
    {"continue", "downgrade", "change_variable", "pause_or_stop"}
)

MASTERY_WRITE_SOURCES = frozenset({"direct_accuracy", "bkt", "fsrs"})
"""The only sources a mastery write may cite. "ai_assisted" is never one."""

FRESHNESS_INTERVAL_DAYS = {"fast": 30, "medium": 60, "slow": 120}
"""Recheck tier by how fast the material changes (days)."""


# ── helpers ───────────────────────────────────────────────────────────────


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)) or False


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _parse_date(value: object) -> Optional[date]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _issue(issues: list, gate: str, field: str, code: str, message: str) -> None:
    issues.append({"gate": gate, "field": field, "code": code, "message": message})


def _check_sample(
    sample: object, issues: list, gate: str, field: str
) -> Optional[Mapping[str, Any]]:
    """A sample must be an object with a task, an independent result and an outcome."""
    if not isinstance(sample, Mapping):
        _issue(issues, gate, field, "not_an_object", "sample must be an object")
        return None
    if not _non_empty_str(sample.get("task")):
        _issue(
            issues,
            gate,
            f"{field}.task",
            "missing_task",
            "sample task must be a non-empty string",
        )
    if not _non_empty_str(sample.get("independent_result")):
        _issue(
            issues,
            gate,
            f"{field}.independent_result",
            "missing_independent_result",
            "sample must record what the learner did independently",
        )
    if sample.get("outcome") not in ("pass", "fail", "partial"):
        _issue(
            issues,
            gate,
            f"{field}.outcome",
            "bad_outcome",
            "sample outcome must be pass, fail or partial",
        )
    if not _non_empty_str(sample.get("evidence_location")):
        _issue(
            issues,
            gate,
            f"{field}.evidence_location",
            "missing_evidence_location",
            "sample must point at its raw evidence",
        )
    return sample


def _normalize_ledger_result(result: object) -> tuple[bool, list]:
    """Accept a ledger_check result as an object with .passed or a dict."""
    if isinstance(result, Mapping):
        return bool(result.get("passed")), list(result.get("issues") or [])
    passed = bool(getattr(result, "passed", False))
    return passed, list(getattr(result, "issues", []) or [])


# ── G1 · learner evidence chain ───────────────────────────────────────────


def verify_evidence_chain(
    chain: object,
    *,
    known_ku_ids: Optional[set] = None,
    ledger_check: Optional[Callable[[Mapping[str, Any]], Any]] = None,
) -> dict:
    """Gate one learner evidence chain (G1). Fail-closed; every failure lists its cause.

    The chain keeps one question across four time points: baseline (before
    any tool or help), immediate, delayed retention (prompts removed) and
    transfer (one condition changed). Fact / explanation / hypothesis must
    live in separate columns, and at most one condition may change per
    round. ``ledger_check``, when the chain carries a source ledger, is the
    injected G1 ledger gate (same shape as aetherviz g10): un-injected, a
    ledger-carrying chain fails instead of passing silently.
    """
    issues: list = []
    if not isinstance(chain, Mapping):
        return {
            "passed": False,
            "issues": [
                {
                    "gate": "e1",
                    "field": "",
                    "code": "not_an_object",
                    "message": "chain must be an object",
                }
            ],
            "conflict": False,
            "samples_checked": 0,
        }
    if not _non_empty_str(chain.get("question")):
        _issue(
            issues,
            "e1",
            "question",
            "missing_question",
            "chain question must be a non-empty string",
        )
    if not _non_empty_str(chain.get("completion_standard")):
        _issue(
            issues,
            "e1",
            "completion_standard",
            "missing_completion_standard",
            "completion standard must be a non-empty string",
        )
    samples = chain.get("samples")
    if not isinstance(samples, Mapping):
        _issue(
            issues,
            "e1",
            "samples",
            "missing_samples",
            "samples must be an object with baseline, immediate, delayed and transfer",
        )
        samples = {}
    for key in ("baseline", "immediate", "delayed", "transfer"):
        if key not in samples:
            _issue(
                issues,
                "e1",
                f"samples.{key}",
                "missing_sample",
                f"{key} sample is required",
            )

    baseline = (
        _check_sample(samples.get("baseline"), issues, "e2", "samples.baseline")
        if "baseline" in samples
        else None
    )
    if isinstance(baseline, Mapping):
        tools = baseline.get("tools_used")
        if tools is None:
            _issue(
                issues,
                "e2",
                "samples.baseline.tools_used",
                "missing_tools_used",
                "baseline must record which tools were used (empty when none)",
            )
        elif not isinstance(tools, list) or tools:
            _issue(
                issues,
                "e2",
                "samples.baseline.tools_used",
                "baseline_not_clean",
                "baseline must happen before any tool or help; tools_used must be an empty list",
            )

    immediate = (
        _check_sample(samples.get("immediate"), issues, "e3", "samples.immediate")
        if "immediate" in samples
        else None
    )
    if isinstance(immediate, Mapping) and not _non_empty_str(
        immediate.get("conditions")
    ):
        _issue(
            issues,
            "e3",
            "samples.immediate.conditions",
            "missing_conditions",
            "immediate sample must record its conditions and prompts",
        )

    delayed = (
        _check_sample(samples.get("delayed"), issues, "e4", "samples.delayed")
        if "delayed" in samples
        else None
    )
    if isinstance(delayed, Mapping):
        delay = delayed.get("delay_days")
        if not _is_int(delay) or delay < 1:
            _issue(
                issues,
                "e4",
                "samples.delayed.delay_days",
                "bad_delay_days",
                "delayed retention needs delay_days of at least 1",
            )
        removed = delayed.get("prompts_removed")
        if (
            not isinstance(removed, list)
            or not removed
            or not all(_non_empty_str(x) for x in removed)
        ):
            _issue(
                issues,
                "e4",
                "samples.delayed.prompts_removed",
                "prompts_not_removed",
                "delayed retention must list the prompts that were removed",
            )
        changed = delayed.get("changed")
        if changed is not None and (not isinstance(changed, list) or len(changed) > 1):
            _issue(
                issues,
                "e6",
                "samples.delayed.changed",
                "too_many_changes",
                "at most one condition may change per round",
            )
        d_immediate = (
            _parse_date(immediate.get("date"))
            if isinstance(immediate, Mapping)
            else None
        )
        d_delayed = _parse_date(delayed.get("date"))
        if (
            d_immediate is not None
            and d_delayed is not None
            and d_delayed <= d_immediate
        ):
            _issue(
                issues,
                "e4",
                "samples.delayed.date",
                "delayed_not_after_immediate",
                "delayed date must be after the immediate date",
            )

    transfer = (
        _check_sample(samples.get("transfer"), issues, "e5", "samples.transfer")
        if "transfer" in samples
        else None
    )
    if isinstance(transfer, Mapping):
        condition = transfer.get("changed_condition")
        if condition not in TRANSFER_CONDITIONS:
            _issue(
                issues,
                "e5",
                "samples.transfer.changed_condition",
                "bad_changed_condition",
                "transfer must name one changed condition from the allowed set",
            )
        changed = transfer.get("changed")
        if changed is not None and (not isinstance(changed, list) or len(changed) > 1):
            _issue(
                issues,
                "e6",
                "samples.transfer.changed",
                "too_many_changes",
                "at most one condition may change per round",
            )
        elif (
            isinstance(changed, list)
            and condition in TRANSFER_CONDITIONS
            and changed != [condition]
        ):
            _issue(
                issues,
                "e6",
                "samples.transfer.changed",
                "changed_mismatch",
                "transfer changed list must name exactly its changed_condition",
            )

    statements = chain.get("statements")
    if not isinstance(statements, Mapping):
        _issue(
            issues,
            "e7",
            "statements",
            "missing_statements",
            "statements must separate fact, explanation and hypothesis",
        )
        statements = {}
    seen_texts: dict = {}
    for column in ("fact", "explanation", "hypothesis"):
        items = statements.get(column)
        if (
            not isinstance(items, list)
            or not items
            or not all(_non_empty_str(x) for x in items)
        ):
            _issue(
                issues,
                "e7",
                f"statements.{column}",
                "empty_column",
                f"{column} column must be a non-empty list of statements",
            )
            continue
        for text in items:
            if text in seen_texts and seen_texts[text] != column:
                _issue(
                    issues,
                    "e7",
                    f"statements.{column}",
                    "statement_in_two_columns",
                    "one statement must not sit in two columns",
                )
            seen_texts[text] = column
    if not _non_empty_str(statements.get("cannot_conclude")):
        _issue(
            issues,
            "e7",
            "statements.cannot_conclude",
            "missing_cannot_conclude",
            "chain must state what cannot be concluded",
        )

    conflict = bool(
        isinstance(immediate, Mapping)
        and isinstance(delayed, Mapping)
        and immediate.get("outcome") == "pass"
        and delayed.get("outcome") == "fail"
    )
    decision = chain.get("decision")
    if not isinstance(decision, Mapping):
        _issue(
            issues, "e8", "decision", "missing_decision", "decision must be an object"
        )
        decision = {}
    verdict = decision.get("verdict")
    if verdict not in CHAIN_DECISIONS:
        _issue(
            issues,
            "e8",
            "decision.verdict",
            "bad_verdict",
            "decision verdict must be continue, downgrade, change_variable or pause_or_stop",
        )
    if not _non_empty_str(decision.get("next_minimal_task")):
        _issue(
            issues,
            "e8",
            "decision.next_minimal_task",
            "missing_next_task",
            "decision must name the next minimal task",
        )
    if _parse_date(decision.get("next_review_date")) is None:
        _issue(
            issues,
            "e8",
            "decision.next_review_date",
            "bad_next_review_date",
            "decision needs a next review date (YYYY-MM-DD)",
        )
    if verdict not in (None, "pause_or_stop") and not _non_empty_str(
        decision.get("one_changed_condition")
    ):
        _issue(
            issues,
            "e8",
            "decision.one_changed_condition",
            "missing_one_changed_condition",
            "the next round must change exactly one condition",
        )
    if (
        conflict
        and verdict == "continue"
        and decision.get("conflict_acknowledged") is not True
    ):
        _issue(
            issues,
            "e8",
            "decision.verdict",
            "conflict_ignored",
            "immediate passed but delayed failed; continuing needs conflict_acknowledged",
        )

    if "ledger" in chain:
        if ledger_check is None:
            _issue(
                issues,
                "e1",
                "ledger",
                "ledger_gate_unavailable",
                "chain carries a ledger but no ledger gate was injected",
            )
        else:
            try:
                ledger_passed, ledger_issues = _normalize_ledger_result(
                    ledger_check(chain)
                )
            except Exception as exc:  # noqa: BLE001 - a raising gate must not pass
                _issue(
                    issues,
                    "e1",
                    "ledger",
                    "ledger_check_error",
                    f"ledger gate raised {type(exc).__name__}",
                )
            else:
                if not ledger_passed:
                    for item in ledger_issues:
                        if isinstance(item, Mapping):
                            _issue(
                                issues,
                                "e1",
                                "ledger",
                                str(item.get("code", "ledger_failed")),
                                str(item.get("message", "ledger gate failed")),
                            )
                        else:
                            _issue(issues, "e1", "ledger", "ledger_failed", str(item))

    return {
        "passed": not issues,
        "issues": issues,
        "conflict": conflict,
        "samples_checked": sum(
            1
            for key in ("baseline", "immediate", "delayed", "transfer")
            if key in samples
        ),
    }


# ── G2 · AI-learning log ("three comparisons") ────────────────────────────


def _check_log_sample(
    sample: object, issues: list, gate: str, field: str
) -> Optional[Mapping[str, Any]]:
    """A log sample needs an independent result plus time, rework, confidence and accuracy."""
    sample = _check_sample(sample, issues, gate, field)
    if not isinstance(sample, Mapping):
        return None
    for name in ("time_minutes", "rework", "confidence", "accuracy"):
        value = sample.get(name)
        if not _is_num(value) or value < 0:
            _issue(
                issues,
                gate,
                f"{field}.{name}",
                "missing_metric",
                f"sample needs a non-negative {name}",
            )
    confidence = sample.get("confidence")
    if _is_num(confidence) and not 0 <= confidence <= 2:
        _issue(
            issues,
            gate,
            f"{field}.confidence",
            "bad_confidence",
            "confidence is scored 0-2",
        )
    accuracy = sample.get("accuracy")
    if _is_num(accuracy) and not 0 <= accuracy <= 1:
        _issue(
            issues,
            gate,
            f"{field}.accuracy",
            "bad_accuracy",
            "accuracy must be between 0 and 1",
        )
    return sample


def verify_ai_learning_log(log: object) -> dict:
    """Gate one AI-learning log (G2). Fail-closed.

    The same task keeps four samples: no-AI baseline, AI-assisted, delayed
    independent (3-7 days) and a parallel task. Speed debt (faster but
    more rework) and miscalibration (confidence up, accuracy down) are
    computed, not asserted, and must be addressed in writing when present.
    The assisted sample can never be written into mastery: only direct
    accuracy, BKT or FSRS may back a mastery write.
    """
    issues: list = []
    if not isinstance(log, Mapping):
        return {
            "passed": False,
            "issues": [
                {
                    "gate": "a1",
                    "field": "",
                    "code": "not_an_object",
                    "message": "log must be an object",
                }
            ],
            "speed_debt": False,
            "miscalibrated": False,
            "mastery_writable_samples": [],
        }
    if not _non_empty_str(log.get("task")):
        _issue(
            issues, "a1", "task", "missing_task", "log task must be a non-empty string"
        )
    if not _non_empty_str(log.get("question")):
        _issue(
            issues,
            "a1",
            "question",
            "missing_question",
            "log must state the one question it answers",
        )
    for key in ("baseline", "assisted", "delayed_independent", "parallel"):
        if key not in log:
            _issue(issues, "a1", key, "missing_sample", f"{key} sample is required")

    baseline = (
        _check_log_sample(log.get("baseline"), issues, "a2", "baseline")
        if "baseline" in log
        else None
    )
    if isinstance(baseline, Mapping):
        if baseline.get("ai_used") is True:
            _issue(
                issues,
                "a2",
                "baseline.ai_used",
                "baseline_not_clean",
                "baseline must be done without AI; ai_used must be false",
            )
        if baseline.get("tools_used") not in (None, []):
            _issue(
                issues,
                "a2",
                "baseline.tools_used",
                "baseline_not_clean",
                "baseline tools_used must be empty",
            )

    scope = log.get("ai_scope")
    if not isinstance(scope, Mapping):
        _issue(
            issues, "a3", "ai_scope", "missing_ai_scope", "ai_scope must be an object"
        )
        scope = {}
    for name in ("model", "version", "date"):
        if not _non_empty_str(scope.get(name)):
            _issue(
                issues,
                "a3",
                f"ai_scope.{name}",
                "missing_scope_field",
                f"ai_scope.{name} must be a non-empty string",
            )
    allowed = scope.get("allowed_actions")
    if (
        not isinstance(allowed, list)
        or not allowed
        or not all(_non_empty_str(x) for x in allowed)
    ):
        _issue(
            issues,
            "a3",
            "ai_scope.allowed_actions",
            "empty_allowed_actions",
            "ai_scope must list what AI is allowed to do",
        )
    forbidden = scope.get("forbidden_actions")
    if not isinstance(forbidden, list) or "final_fact_judgement" not in forbidden:
        _issue(
            issues,
            "a3",
            "ai_scope.forbidden_actions",
            "final_judgement_not_forbidden",
            "final fact judgement must be forbidden to AI",
        )
    if "final_fact_judgement" in (allowed or []):
        _issue(
            issues,
            "a3",
            "ai_scope.allowed_actions",
            "final_judgement_allowed",
            "final fact judgement must not be an allowed AI action",
        )
    if not _non_empty_str(scope.get("min_material")):
        _issue(
            issues,
            "a3",
            "ai_scope.min_material",
            "missing_min_material",
            "ai_scope must state the minimal material sent to the model",
        )

    assisted = (
        _check_log_sample(log.get("assisted"), issues, "a4", "assisted")
        if "assisted" in log
        else None
    )
    if isinstance(assisted, Mapping):
        actions = assisted.get("ai_actions")
        if (
            not isinstance(actions, list)
            or not actions
            or not all(_non_empty_str(x) for x in actions)
        ):
            _issue(
                issues,
                "a4",
                "assisted.ai_actions",
                "missing_ai_actions",
                "assisted sample must record what AI actually did",
            )
        if not _non_empty_str(assisted.get("independent_after_off")):
            _issue(
                issues,
                "a4",
                "assisted.independent_after_off",
                "missing_independent_after_off",
                "assisted sample must record what the learner did after AI was switched off",
            )
        if assisted.get("counts_toward_mastery") is True:
            _issue(
                issues,
                "a8",
                "assisted.counts_toward_mastery",
                "mastery_contaminated",
                "an AI-assisted score must never count toward mastery",
            )

    delayed = (
        _check_log_sample(
            log.get("delayed_independent"), issues, "a5", "delayed_independent"
        )
        if "delayed_independent" in log
        else None
    )
    if isinstance(delayed, Mapping):
        delay = delayed.get("delay_days")
        if not _is_int(delay) or not 3 <= delay <= 7:
            _issue(
                issues,
                "a5",
                "delayed_independent.delay_days",
                "bad_delay_days",
                "delayed independent sample needs delay_days between 3 and 7",
            )
        removed = delayed.get("prompts_removed")
        if (
            not isinstance(removed, list)
            or not removed
            or not all(_non_empty_str(x) for x in removed)
        ):
            _issue(
                issues,
                "a5",
                "delayed_independent.prompts_removed",
                "prompts_not_removed",
                "delayed independent sample must list the prompts that were removed",
            )

    parallel = (
        _check_log_sample(log.get("parallel"), issues, "a6", "parallel")
        if "parallel" in log
        else None
    )
    if (
        isinstance(parallel, Mapping)
        and parallel.get("changed_condition") not in TRANSFER_CONDITIONS
    ):
        _issue(
            issues,
            "a6",
            "parallel.changed_condition",
            "bad_changed_condition",
            "parallel task must name one changed condition from the allowed set",
        )

    speed_debt = False
    miscalibrated = False
    if isinstance(baseline, Mapping) and isinstance(assisted, Mapping):
        if (
            _is_num(baseline.get("time_minutes"))
            and _is_num(assisted.get("time_minutes"))
            and _is_num(baseline.get("rework"))
            and _is_num(assisted.get("rework"))
            and assisted["time_minutes"] < baseline["time_minutes"]
            and assisted["rework"] > baseline["rework"]
        ):
            speed_debt = True
        if (
            _is_num(baseline.get("confidence"))
            and _is_num(assisted.get("confidence"))
            and _is_num(baseline.get("accuracy"))
            and _is_num(assisted.get("accuracy"))
            and assisted["confidence"] > baseline["confidence"]
            and assisted["accuracy"] < baseline["accuracy"]
        ):
            miscalibrated = True
    if speed_debt and not _non_empty_str(log.get("speed_debt_note")):
        _issue(
            issues,
            "a7",
            "speed_debt_note",
            "speed_debt_unaddressed",
            "assisted was faster but needed more rework; the speed debt must be addressed in writing",
        )
    if miscalibrated and not _non_empty_str(log.get("calibration_note")):
        _issue(
            issues,
            "a7",
            "calibration_note",
            "miscalibration_unaddressed",
            "confidence rose while accuracy fell; the miscalibration must be addressed in writing",
        )

    mastery_write = log.get("mastery_write")
    if isinstance(mastery_write, Mapping):
        source = mastery_write.get("source")
        if source not in MASTERY_WRITE_SOURCES:
            _issue(
                issues,
                "a8",
                "mastery_write.source",
                "bad_mastery_source",
                "mastery may only be written from direct_accuracy, bkt or fsrs, never from ai_assisted",
            )
    return {
        "passed": not issues,
        "issues": issues,
        "speed_debt": speed_debt,
        "miscalibrated": miscalibrated,
        "mastery_writable_samples": ["baseline", "delayed_independent", "parallel"],
    }


# ── G3 · AI task brief + evaluation record ────────────────────────────────


def verify_ai_task_brief(brief: object) -> dict:
    """Gate an AI task brief (G3, part 1). Fail-closed.

    The eval set is fixed before any run: every required case kind must be
    present with an expected and an unacceptable outcome, and the freeze
    date is recorded so a later evaluation can prove it ran after the set
    was frozen. Human gates, cost cap, rollback, long-task recovery,
    isolation and policy fields are all required where they apply.
    """
    issues: list = []
    if not isinstance(brief, Mapping):
        return {
            "passed": False,
            "issues": [
                {
                    "gate": "b1",
                    "field": "",
                    "code": "not_an_object",
                    "message": "brief must be an object",
                }
            ],
            "eval_case_ids": [],
        }
    task = brief.get("task")
    if not isinstance(task, Mapping):
        _issue(issues, "b1", "task", "missing_task", "task must be an object")
        task = {}
    for name in (
        "scenario",
        "audience",
        "action",
        "deadline",
        "owner",
        "human_reviewer",
    ):
        if not _non_empty_str(task.get(name)):
            _issue(
                issues,
                "b1",
                f"task.{name}",
                "missing_task_field",
                f"task.{name} must be a non-empty string",
            )

    inputs = brief.get("inputs")
    if not isinstance(inputs, Mapping):
        _issue(issues, "b2", "inputs", "missing_inputs", "inputs must be an object")
        inputs = {}
    if inputs.get("sensitivity") not in SENSITIVITY_LEVELS:
        _issue(
            issues,
            "b2",
            "inputs.sensitivity",
            "bad_sensitivity",
            "sensitivity must be public, internal, confidential or restricted",
        )
    allowed_fields = inputs.get("allowed_fields")
    if (
        not isinstance(allowed_fields, list)
        or not allowed_fields
        or not all(_non_empty_str(x) for x in allowed_fields)
    ):
        _issue(
            issues,
            "b2",
            "inputs.allowed_fields",
            "empty_allowed_fields",
            "inputs must list the allowed fields",
        )
    forbidden_material = inputs.get("forbidden_material")
    if (
        not isinstance(forbidden_material, list)
        or not forbidden_material
        or not all(_non_empty_str(x) for x in forbidden_material)
    ):
        _issue(
            issues,
            "b2",
            "inputs.forbidden_material",
            "empty_forbidden_material",
            "inputs must list the material that must not be provided",
        )
    if inputs.get("consent") in (None, "", False):
        _issue(
            issues,
            "b2",
            "inputs.consent",
            "missing_consent",
            "inputs must record consent for the data used",
        )
    if not _non_empty_str(inputs.get("retention")):
        _issue(
            issues,
            "b2",
            "inputs.retention",
            "missing_retention",
            "inputs must record collection, transfer, retention and deletion limits",
        )

    eval_set = brief.get("eval_set")
    if not isinstance(eval_set, Mapping):
        _issue(
            issues, "b3", "eval_set", "missing_eval_set", "eval_set must be an object"
        )
        eval_set = {}
    if _parse_date(eval_set.get("frozen_at")) is None:
        _issue(
            issues,
            "b3",
            "eval_set.frozen_at",
            "bad_frozen_at",
            "eval_set needs a freeze date (YYYY-MM-DD)",
        )
    cases = eval_set.get("cases")
    case_ids: list = []
    if not isinstance(cases, list) or not cases:
        _issue(
            issues,
            "b3",
            "eval_set.cases",
            "empty_eval_set",
            "eval_set needs a non-empty case list",
        )
        cases = []
    kinds_seen: set = set()
    for pos, case in enumerate(cases):
        field = f"eval_set.cases[{pos}]"
        if not isinstance(case, Mapping):
            _issue(issues, "b3", field, "not_an_object", "eval case must be an object")
            continue
        if not _non_empty_str(case.get("id")):
            _issue(
                issues, "b3", f"{field}.id", "missing_case_id", "eval case needs an id"
            )
        elif case["id"] in case_ids:
            _issue(
                issues,
                "b3",
                f"{field}.id",
                "duplicate_case_id",
                "eval case ids must be unique",
            )
        else:
            case_ids.append(case["id"])
        kind = case.get("kind")
        kinds_seen.add(kind)
        if kind not in EVAL_CASE_KINDS:
            _issue(
                issues,
                "b3",
                f"{field}.kind",
                "bad_case_kind",
                "eval case kind must be normal, boundary, missing, conflict or desensitised_historical",
            )
        for name in ("expected", "unacceptable"):
            if not _non_empty_str(case.get(name)):
                _issue(
                    issues,
                    "b3",
                    f"{field}.{name}",
                    "missing_case_field",
                    f"eval case needs a non-empty {name}",
                )
    for kind in sorted(EVAL_CASE_KINDS - kinds_seen):
        _issue(
            issues,
            "b3",
            "eval_set.cases",
            "missing_case_kind",
            f"eval set has no {kind} case",
        )

    scope = brief.get("ai_scope")
    if not isinstance(scope, Mapping):
        _issue(
            issues, "b4", "ai_scope", "missing_ai_scope", "ai_scope must be an object"
        )
        scope = {}
    allowed_actions = scope.get("allowed_actions")
    if (
        not isinstance(allowed_actions, list)
        or not allowed_actions
        or not all(_non_empty_str(x) for x in allowed_actions)
    ):
        _issue(
            issues,
            "b4",
            "ai_scope.allowed_actions",
            "empty_allowed_actions",
            "ai_scope must list what AI is allowed to do",
        )
    forbidden_actions = scope.get("forbidden_actions")
    if (
        not isinstance(forbidden_actions, list)
        or "final_fact_judgement" not in forbidden_actions
    ):
        _issue(
            issues,
            "b4",
            "ai_scope.forbidden_actions",
            "final_judgement_not_forbidden",
            "final fact judgement must be forbidden to AI",
        )
    if "final_fact_judgement" in (allowed_actions or []):
        _issue(
            issues,
            "b4",
            "ai_scope.allowed_actions",
            "final_judgement_allowed",
            "final fact judgement must not be an allowed AI action",
        )
    for name in ("model", "version", "region", "date"):
        if not _non_empty_str(scope.get(name)):
            _issue(
                issues,
                "b4",
                f"ai_scope.{name}",
                "missing_scope_field",
                f"ai_scope.{name} must be a non-empty string",
            )

    gates = brief.get("human_gates")
    gates_seen: set = set()
    if not isinstance(gates, list) or not gates:
        _issue(
            issues,
            "b5",
            "human_gates",
            "empty_human_gates",
            "human_gates must be a non-empty list",
        )
        gates = []
    for pos, gate in enumerate(gates):
        field = f"human_gates[{pos}]"
        if not isinstance(gate, Mapping):
            _issue(issues, "b5", field, "not_an_object", "human gate must be an object")
            continue
        name = gate.get("gate")
        gates_seen.add(name)
        if name not in REQUIRED_HUMAN_GATES:
            _issue(
                issues,
                "b5",
                f"{field}.gate",
                "bad_human_gate",
                "human gate name is not one of the required gates",
            )
        if not _non_empty_str(gate.get("reviewer")):
            _issue(
                issues,
                "b5",
                f"{field}.reviewer",
                "missing_reviewer",
                "each human gate needs a named reviewer",
            )
        if not _non_empty_str(gate.get("evidence")):
            _issue(
                issues,
                "b5",
                f"{field}.evidence",
                "missing_gate_evidence",
                "each human gate needs its pass evidence",
            )
    for name in sorted(REQUIRED_HUMAN_GATES - gates_seen):
        _issue(
            issues,
            "b5",
            "human_gates",
            "missing_human_gate",
            f"human gate {name} is required",
        )

    cost_cap = brief.get("cost_cap")
    if not isinstance(cost_cap, Mapping):
        _issue(
            issues, "b6", "cost_cap", "missing_cost_cap", "cost_cap must be an object"
        )
        cost_cap = {}
    amount = cost_cap.get("amount")
    minutes = cost_cap.get("minutes_cap")
    if (not _is_num(amount) or amount <= 0) and (not _is_num(minutes) or minutes <= 0):
        _issue(
            issues,
            "b6",
            "cost_cap",
            "no_cost_cap",
            "cost_cap needs a positive amount or minutes cap",
        )
    if not _non_empty_str(brief.get("rollback")):
        _issue(
            issues,
            "b6",
            "rollback",
            "missing_rollback",
            "brief must state the rollback plan",
        )

    if brief.get("long_running") is True:
        long_task = brief.get("long_task")
        if not isinstance(long_task, Mapping):
            _issue(
                issues,
                "b7",
                "long_task",
                "missing_long_task",
                "a long-running task needs long_task recovery fields",
            )
            long_task = {}
        for name in ("run_id", "idempotency_key", "handover_point"):
            if not _non_empty_str(long_task.get(name)):
                _issue(
                    issues,
                    "b7",
                    f"long_task.{name}",
                    "missing_long_task_field",
                    f"long_task.{name} must be a non-empty string",
                )
        checkpoints = long_task.get("checkpoints")
        if (
            not isinstance(checkpoints, list)
            or not checkpoints
            or not all(_non_empty_str(x) for x in checkpoints)
        ):
            _issue(
                issues,
                "b7",
                "long_task.checkpoints",
                "missing_checkpoints",
                "long_task needs a non-empty checkpoint list",
            )
        timeout = long_task.get("timeout_minutes")
        if not _is_num(timeout) or timeout <= 0:
            _issue(
                issues,
                "b7",
                "long_task.timeout_minutes",
                "bad_timeout",
                "long_task needs a positive timeout in minutes",
            )
        retries = long_task.get("max_retries")
        if not _is_int(retries) or retries < 0:
            _issue(
                issues,
                "b7",
                "long_task.max_retries",
                "bad_max_retries",
                "long_task needs max_retries as a non-negative integer",
            )

    isolation = brief.get("isolation")
    if not isinstance(isolation, Mapping):
        _issue(
            issues,
            "b8",
            "isolation",
            "missing_isolation",
            "isolation must be an object",
        )
        isolation = {}
    if not isinstance(isolation.get("egress_whitelist"), list):
        _issue(
            issues,
            "b8",
            "isolation.egress_whitelist",
            "missing_egress_whitelist",
            "isolation needs an egress whitelist (empty list when no network use)",
        )
    if not _non_empty_str(isolation.get("credential_scope")):
        _issue(
            issues,
            "b8",
            "isolation.credential_scope",
            "missing_credential_scope",
            "isolation needs a credential scope",
        )
    if isolation.get("untrusted_browser_input") is not True:
        _issue(
            issues,
            "b8",
            "isolation.untrusted_browser_input",
            "browser_input_trusted",
            "browser pages and screenshots must be treated as untrusted input",
        )
    policy = brief.get("policy")
    if not isinstance(policy, Mapping):
        _issue(issues, "b8", "policy", "missing_policy", "policy must be an object")
        policy = {}
    for name in ("name", "version", "region"):
        if not _non_empty_str(policy.get(name)):
            _issue(
                issues,
                "b8",
                f"policy.{name}",
                "missing_policy_field",
                f"policy.{name} must be a non-empty string",
            )
    if _parse_date(policy.get("effective_date")) is None:
        _issue(
            issues,
            "b8",
            "policy.effective_date",
            "bad_effective_date",
            "policy needs an effective date (YYYY-MM-DD)",
        )
    if not isinstance(policy.get("high_risk_human_review"), bool):
        _issue(
            issues,
            "b8",
            "policy.high_risk_human_review",
            "missing_high_risk_review",
            "policy must say whether high-risk work gets human review",
        )

    return {"passed": not issues, "issues": issues, "eval_case_ids": case_ids}


def verify_ai_evaluation(
    record: object, brief: Optional[Mapping[str, Any]] = None
) -> dict:
    """Gate one AI evaluation record (G3, part 2). Fail-closed.

    Rates are recomputed from the per-case attempts, so failures and
    timeouts cannot be dropped from the denominator; first-pass and
    post-human-revision rates stay separate. Cost is prep + run + verify
    + rework, and a zero qualified count makes cost-per-qualified
    "not_computable", never zero. When a brief is given, the record must
    run the exact frozen eval set, on or after its freeze date.
    """
    issues: list = []
    if not isinstance(record, Mapping):
        return {
            "passed": False,
            "issues": [
                {
                    "gate": "v1",
                    "field": "",
                    "code": "not_an_object",
                    "message": "record must be an object",
                }
            ],
            "first_pass_rate": None,
            "post_revision_rate": None,
            "total_minutes": None,
            "cost_per_qualified": None,
        }
    if not _non_empty_str(record.get("version")):
        _issue(
            issues,
            "v1",
            "version",
            "missing_version",
            "record needs the version under test",
        )
    run_date = _parse_date(record.get("run_date"))
    if run_date is None:
        _issue(
            issues,
            "v1",
            "run_date",
            "bad_run_date",
            "record needs a run date (YYYY-MM-DD)",
        )

    cases = record.get("eval_cases")
    if not isinstance(cases, list) or not cases:
        _issue(
            issues,
            "v1",
            "eval_cases",
            "empty_eval_cases",
            "record needs a non-empty eval case list",
        )
        cases = []
    total = 0
    first_pass_count = 0
    post_revision_count = 0
    seen_case_ids: list = []
    for pos, case in enumerate(cases):
        field = f"eval_cases[{pos}]"
        if not isinstance(case, Mapping):
            _issue(
                issues,
                "v1",
                field,
                "not_an_object",
                "eval case attempt must be an object",
            )
            continue
        total += 1
        case_id = case.get("case_id")
        if not _non_empty_str(case_id):
            _issue(
                issues,
                "v1",
                f"{field}.case_id",
                "missing_case_id",
                "eval case attempt needs a case_id",
            )
        elif case_id in seen_case_ids:
            _issue(
                issues,
                "v1",
                f"{field}.case_id",
                "duplicate_case_attempt",
                "one attempt per case id in this record",
            )
        else:
            seen_case_ids.append(case_id)
        if not _non_empty_str(case.get("expected")):
            _issue(
                issues,
                "v1",
                f"{field}.expected",
                "missing_expected",
                "eval case attempt needs its expected behaviour",
            )
        if not _non_empty_str(case.get("actual")):
            _issue(
                issues,
                "v1",
                f"{field}.actual",
                "missing_actual",
                "eval case attempt needs its actual behaviour",
            )
        if case.get("first_pass") is True:
            first_pass_count += 1
        elif case.get("first_pass") is not True and case.get("first_pass") is not False:
            _issue(
                issues,
                "v3",
                f"{field}.first_pass",
                "missing_first_pass",
                "each attempt must record first_pass as true or false",
            )
        if case.get("final_status") == "pass":
            post_revision_count += 1
        elif case.get("final_status") not in ("pass", "fail", "timeout"):
            _issue(
                issues,
                "v3",
                f"{field}.final_status",
                "bad_final_status",
                "final_status must be pass, fail or timeout",
            )
        if case.get("hard_gate_failed") is True and case.get("first_pass") is True:
            _issue(
                issues,
                "v2",
                f"{field}.first_pass",
                "hard_gate_contradiction",
                "a hard-gate failure cannot count as a first pass",
            )

    if brief is not None:
        brief_check = verify_ai_task_brief(brief)
        if not brief_check["passed"]:
            _issue(
                issues,
                "v1",
                "brief",
                "brief_invalid",
                "the brief the record cites does not pass its own gate",
            )
        else:
            frozen = _parse_date(brief["eval_set"].get("frozen_at"))
            if run_date is not None and frozen is not None and run_date < frozen:
                _issue(
                    issues,
                    "v1",
                    "run_date",
                    "ran_before_freeze",
                    "evaluation ran before its eval set was frozen",
                )
            if set(seen_case_ids) != set(brief_check["eval_case_ids"]):
                _issue(
                    issues,
                    "v1",
                    "eval_cases",
                    "eval_set_mismatch",
                    "record must run exactly the brief's frozen eval set",
                )
        if brief.get("long_running") is True:
            for name in ("run_id", "checkpoints", "idempotency_key"):
                if record.get(name) in (None, "", []):
                    _issue(
                        issues,
                        "v5",
                        name,
                        "missing_long_task_field",
                        f"long-running record needs {name}",
                    )

    hard_gates = record.get("hard_gates")
    if not isinstance(hard_gates, list) or not hard_gates:
        _issue(
            issues,
            "v2",
            "hard_gates",
            "empty_hard_gates",
            "record needs its hard gates listed",
        )
        hard_gates = []
    for pos, gate in enumerate(hard_gates):
        if not isinstance(gate, Mapping) or not _non_empty_str(gate.get("name")):
            _issue(
                issues,
                "v2",
                f"hard_gates[{pos}]",
                "bad_hard_gate",
                "hard gate needs a name",
            )
        elif gate.get("passed") is not True:
            _issue(
                issues,
                "v2",
                f"hard_gates[{pos}]",
                "hard_gate_failed",
                f"hard gate {gate.get('name')} failed; the version does not qualify",
            )

    summary = record.get("summary")
    if not isinstance(summary, Mapping):
        _issue(
            issues,
            "v3",
            "summary",
            "missing_summary",
            "record needs a summary with recomputed rates",
        )
        summary = {}
    if total:
        if summary.get("total_attempts") not in (None, total):
            _issue(
                issues,
                "v3",
                "summary.total_attempts",
                "denominator_mismatch",
                "total_attempts must count every attempt, failures and timeouts included",
            )
        if summary.get("first_pass_count") not in (None, first_pass_count):
            _issue(
                issues,
                "v3",
                "summary.first_pass_count",
                "first_pass_mismatch",
                "first_pass_count does not match the per-case attempts",
            )
        if summary.get("post_revision_count") not in (None, post_revision_count):
            _issue(
                issues,
                "v3",
                "summary.post_revision_count",
                "post_revision_mismatch",
                "post_revision_count does not match the per-case attempts",
            )

    costs = record.get("costs")
    total_minutes: Optional[float] = None
    if not isinstance(costs, Mapping):
        _issue(
            issues,
            "v4",
            "costs",
            "missing_costs",
            "record needs its full cost accounting",
        )
        costs = {}
    parts = [
        costs.get(k)
        for k in ("prep_minutes", "run_minutes", "verify_minutes", "rework_minutes")
    ]
    if any(not _is_num(p) or p < 0 for p in parts):
        _issue(
            issues,
            "v4",
            "costs",
            "bad_cost_parts",
            "costs need non-negative prep, run, verify and rework minutes",
        )
    else:
        total_minutes = float(sum(parts))  # type: ignore[arg-type]
        if costs.get("total_minutes") not in (None, total_minutes):
            _issue(
                issues,
                "v4",
                "costs.total_minutes",
                "total_minutes_mismatch",
                "total_minutes must equal prep + run + verify + rework",
            )
    tool_cost = costs.get("tool_cost")
    if not _is_num(tool_cost) or tool_cost < 0:
        _issue(
            issues,
            "v4",
            "costs.tool_cost",
            "bad_tool_cost",
            "costs need a non-negative tool_cost",
        )
    cost_per_qualified: object = None
    if post_revision_count == 0:
        if costs.get("cost_per_qualified") not in (None, "not_computable"):
            _issue(
                issues,
                "v4",
                "costs.cost_per_qualified",
                "zero_qualified_cost",
                "with zero qualified results, cost per qualified is not_computable, never zero",
            )
        cost_per_qualified = "not_computable"
    elif _is_num(tool_cost) and total_minutes is not None:
        labour_rate = costs.get("labour_rate_per_hour")
        total_cost = float(tool_cost)
        if _is_num(labour_rate):
            total_cost += total_minutes / 60.0 * float(labour_rate)
        cost_per_qualified = total_cost / post_revision_count
        claimed = costs.get("cost_per_qualified")
        if claimed is not None and (
            not _is_num(claimed)
            or abs(float(claimed) - float(cost_per_qualified)) > 0.01
        ):
            _issue(
                issues,
                "v4",
                "costs.cost_per_qualified",
                "cost_per_qualified_mismatch",
                "cost_per_qualified does not match the recomputed cost",
            )

    decision = record.get("decision")
    if not isinstance(decision, Mapping):
        _issue(issues, "v6", "decision", "missing_decision", "record needs a decision")
        decision = {}
    if decision.get("verdict") not in EVAL_DECISIONS:
        _issue(
            issues,
            "v6",
            "decision.verdict",
            "bad_decision",
            "decision must be adopt, keep_status_quo, fix_and_retest or stop",
        )
    if decision.get("verdict") == "adopt" and any(
        isinstance(g, Mapping) and g.get("passed") is not True for g in hard_gates
    ):
        _issue(
            issues,
            "v6",
            "decision.verdict",
            "adopt_with_failed_gate",
            "adopt requires every hard gate to pass",
        )
    supporting = decision.get("supporting_cases")
    if (
        not isinstance(supporting, list)
        or not supporting
        or not all(_non_empty_str(x) for x in supporting)
    ):
        _issue(
            issues,
            "v6",
            "decision.supporting_cases",
            "missing_supporting_cases",
            "decision needs its supporting case ids",
        )

    first_rate = (first_pass_count / total) if total else None
    post_rate = (post_revision_count / total) if total else None
    return {
        "passed": not issues,
        "issues": issues,
        "first_pass_rate": first_rate,
        "post_revision_rate": post_rate,
        "total_minutes": total_minutes,
        "cost_per_qualified": cost_per_qualified,
    }


# ── G4 · source freshness / recheck interval ──────────────────────────────


def freshness_interval_days(change_speed: str) -> int:
    """Recheck interval in days for a change-speed tier (30 / 60 / 120)."""
    if change_speed not in FRESHNESS_INTERVAL_DAYS:
        raise ValueError("change_speed must be fast, medium or slow")
    return FRESHNESS_INTERVAL_DAYS[change_speed]


def verify_source_freshness(
    source: object,
    *,
    as_of: Optional[str] = None,
    require_current: bool = False,
    previous: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Gate one source's freshness (G4). Fail-closed.

    ``sources_checked`` (verification date) and ``updated`` (modification
    date) stay separate: a source verified before its last edit is stale,
    and moving ``updated`` forward while ``sources_checked`` stands still
    is a date bump without a recheck, not a completed review. Past its
    tier interval a source must be marked historical and no longer counts
    as current evidence. ``as_of`` defaults to today.
    """
    issues: list = []
    if not isinstance(source, Mapping):
        return {
            "passed": False,
            "issues": [
                {
                    "gate": "s1",
                    "field": "",
                    "code": "not_an_object",
                    "message": "source must be an object",
                }
            ],
            "interval_days": None,
            "age_days": None,
            "due_date": None,
            "counts_as_current_evidence": False,
        }
    if not _non_empty_str(source.get("id")):
        _issue(issues, "s1", "id", "missing_id", "source needs an id")
    if not _non_empty_str(source.get("url")):
        _issue(
            issues,
            "s1",
            "url",
            "missing_url",
            "source needs a url that can be rechecked",
        )
    change_speed = source.get("change_speed")
    interval: Optional[int] = None
    if change_speed not in FRESHNESS_INTERVAL_DAYS:
        _issue(
            issues,
            "s1",
            "change_speed",
            "bad_change_speed",
            "change_speed must be fast, medium or slow",
        )
    else:
        interval = FRESHNESS_INTERVAL_DAYS[change_speed]
    checked = _parse_date(source.get("sources_checked"))
    if checked is None:
        _issue(
            issues,
            "s1",
            "sources_checked",
            "bad_sources_checked",
            "sources_checked needs a date (YYYY-MM-DD)",
        )
    updated = _parse_date(source.get("updated"))
    if updated is None:
        _issue(
            issues, "s1", "updated", "bad_updated", "updated needs a date (YYYY-MM-DD)"
        )
    status = source.get("status")
    if status not in ("current", "historical"):
        _issue(
            issues, "s1", "status", "bad_status", "status must be current or historical"
        )

    as_of_date = _parse_date(as_of) if as_of is not None else date.today()
    if as_of is not None and as_of_date is None:
        _issue(issues, "s1", "as_of", "bad_as_of", "as_of needs a date (YYYY-MM-DD)")
        as_of_date = date.today()
    age_days: Optional[int] = None
    due_date: Optional[str] = None
    if checked is not None and updated is not None and checked < updated:
        _issue(
            issues,
            "s2",
            "sources_checked",
            "stale_verification",
            "sources_checked is before the last update; the source was not rechecked after its last edit",
        )
    if checked is not None and not _non_empty_str(source.get("recheck_notes")):
        _issue(
            issues,
            "s2",
            "recheck_notes",
            "missing_recheck_notes",
            "a recheck needs notes saying what was actually checked",
        )
    if checked is not None and as_of_date is not None:
        age_days = (as_of_date - checked).days
        if age_days < 0:
            _issue(
                issues,
                "s2",
                "sources_checked",
                "future_check_date",
                "sources_checked is after as_of",
            )
        if interval is not None:
            from datetime import timedelta

            due_date = (checked + timedelta(days=interval)).isoformat()
            if status == "current" and age_days > interval:
                _issue(
                    issues,
                    "s3",
                    "status",
                    "overdue_recheck",
                    f"source is {age_days} days past its last check (interval {interval} days); mark it historical or recheck it",
                )
    if isinstance(previous, Mapping):
        prev_updated = _parse_date(previous.get("updated"))
        prev_checked = _parse_date(previous.get("sources_checked"))
        if (
            prev_updated is not None
            and updated is not None
            and prev_checked is not None
            and checked is not None
        ):
            if updated != prev_updated and checked == prev_checked:
                _issue(
                    issues,
                    "s4",
                    "updated",
                    "date_bumped_without_recheck",
                    "updated moved forward but sources_checked did not; bumping the date without rechecking does not count",
                )
    counts_as_current = status == "current" and not any(
        i["code"] in ("overdue_recheck", "stale_verification") for i in issues
    )
    if require_current and status != "current":
        _issue(
            issues,
            "s5",
            "status",
            "historical_not_current",
            "a historical source no longer counts as current evidence",
        )
    return {
        "passed": not issues,
        "issues": issues,
        "interval_days": interval,
        "age_days": age_days,
        "due_date": due_date,
        "counts_as_current_evidence": counts_as_current,
    }


# ── examples (synthetic, for tests and authors) ───────────────────────────


def example_evidence_chain() -> dict:
    """A valid evidence chain (synthetic single-pendulum question)."""
    return {
        "question": "Can I explain the small-angle period of a pendulum without notes?",
        "completion_standard": "Explain period, small-angle condition and one worked value, with no prompts.",
        "samples": {
            "baseline": {
                "date": "2026-11-01",
                "task": "Explain the pendulum period from memory.",
                "conditions": "no notes, no prompts",
                "tools_used": [],
                "independent_result": "Stated the period grows with length but could not give the formula.",
                "outcome": "partial",
                "evidence_location": "notebook p.3",
            },
            "immediate": {
                "date": "2026-11-02",
                "task": "Explain the pendulum period after one worked example.",
                "conditions": "worked example visible",
                "tools_used": ["worked example"],
                "independent_result": "Gave the formula and one worked value with the example in view.",
                "outcome": "pass",
                "evidence_location": "notebook p.4",
            },
            "delayed": {
                "date": "2026-11-05",
                "task": "Explain the pendulum period again, prompts removed.",
                "conditions": "prompts removed",
                "tools_used": [],
                "delay_days": 3,
                "prompts_removed": ["worked example", "formula card"],
                "changed": ["prompts"],
                "independent_result": "Gave the formula and the worked value without prompts.",
                "outcome": "pass",
                "evidence_location": "notebook p.5",
            },
            "transfer": {
                "date": "2026-11-06",
                "task": "Explain the pendulum period to a classmate in two minutes.",
                "conditions": "new audience, two-minute limit",
                "tools_used": [],
                "changed_condition": "audience",
                "changed": ["audience"],
                "independent_result": "Explained it to a classmate who could repeat the worked value back.",
                "outcome": "pass",
                "evidence_location": "notebook p.6",
            },
        },
        "statements": {
            "fact": [
                "Baseline on 2026-11-01 could not give the formula.",
                "Delayed sample on 2026-11-05 gave the formula without prompts.",
            ],
            "explanation": [
                "The worked example plus one delayed retest may have stabilised recall."
            ],
            "hypothesis": [
                "A new audience next week will still follow the explanation."
            ],
            "cannot_conclude": "One chain does not prove the method works for every learner.",
        },
        "decision": {
            "verdict": "continue",
            "next_minimal_task": "Explain it to a new audience next week.",
            "one_changed_condition": "audience",
            "next_review_date": "2026-11-13",
        },
    }


def example_ai_learning_log() -> dict:
    """A valid AI-learning log (synthetic; no mastery is written from AI help)."""
    base = {
        "task": "Solve a pendulum period problem.",
        "question": "What did AI help with, and what can I do alone?",
        "baseline": {
            "task": "Solve it without AI.",
            "independent_result": "Set up the problem but used the wrong length.",
            "outcome": "partial",
            "evidence_location": "notebook p.3",
            "time_minutes": 20,
            "rework": 1,
            "confidence": 1,
            "accuracy": 0.5,
        },
        "ai_scope": {
            "model": "example-model",
            "version": "1.0",
            "date": "2026-11-02",
            "allowed_actions": ["diagnose", "ask questions", "give a counterexample"],
            "forbidden_actions": ["final_fact_judgement", "write the full answer"],
            "min_material": "the problem statement only",
        },
        "assisted": {
            "task": "Solve it with AI diagnosing the error.",
            "independent_result": "Solved it after AI pointed at the length error.",
            "outcome": "pass",
            "evidence_location": "notebook p.4",
            "time_minutes": 12,
            "rework": 1,
            "confidence": 2,
            "accuracy": 1.0,
            "ai_actions": ["diagnosed the length error"],
            "independent_after_off": "Re-solved the same problem alone the next morning.",
        },
        "delayed_independent": {
            "task": "Solve a similar problem alone after 4 days.",
            "independent_result": "Solved it alone with the correct length.",
            "outcome": "pass",
            "evidence_location": "notebook p.5",
            "time_minutes": 15,
            "rework": 0,
            "confidence": 2,
            "accuracy": 1.0,
            "delay_days": 4,
            "prompts_removed": ["AI chat", "formula card"],
        },
        "parallel": {
            "task": "Solve a similar problem under a time limit.",
            "independent_result": "Solved it within the limit.",
            "outcome": "pass",
            "evidence_location": "notebook p.6",
            "time_minutes": 10,
            "rework": 0,
            "confidence": 2,
            "accuracy": 1.0,
            "changed_condition": "time_limit",
        },
    }
    return base


def example_ai_task_brief() -> dict:
    """A valid AI task brief (synthetic; long-running, so recovery fields apply)."""
    return {
        "task": {
            "scenario": "A student imports one worked-example file and sees a report that explains its sources and errors.",
            "audience": "one student",
            "action": "Import the file and read the report.",
            "deadline": "2026-12-01",
            "owner": "teacher Li",
            "human_reviewer": "teacher Li",
        },
        "inputs": {
            "sensitivity": "internal",
            "allowed_fields": ["problem statement", "worked steps"],
            "forbidden_material": ["student names", "passwords"],
            "consent": "class consent on file",
            "retention": "kept 30 days, then deleted",
        },
        "eval_set": {
            "frozen_at": "2026-11-20",
            "cases": [
                {
                    "id": "n1",
                    "kind": "normal",
                    "expected": "report lists sources",
                    "unacceptable": "report invents a source",
                },
                {
                    "id": "b1",
                    "kind": "boundary",
                    "expected": "empty file is rejected with a message",
                    "unacceptable": "empty file crashes",
                },
                {
                    "id": "m1",
                    "kind": "missing",
                    "expected": "missing answer is marked missing",
                    "unacceptable": "missing answer is guessed",
                },
                {
                    "id": "c1",
                    "kind": "conflict",
                    "expected": "conflicting steps are flagged",
                    "unacceptable": "one side is silently dropped",
                },
                {
                    "id": "h1",
                    "kind": "desensitised_historical",
                    "expected": "old sample is handled like any other",
                    "unacceptable": "old sample leaks personal data",
                },
            ],
        },
        "ai_scope": {
            "allowed_actions": ["classify", "draft explanation", "suggest checks"],
            "forbidden_actions": ["final_fact_judgement", "publish automatically"],
            "model": "example-model",
            "version": "1.0",
            "region": "cn",
            "date": "2026-11-20",
        },
        "human_gates": [
            {"gate": name, "reviewer": "teacher Li", "evidence": "checklist row"}
            for name in sorted(REQUIRED_HUMAN_GATES)
        ],
        "cost_cap": {"amount": 50, "currency": "CNY"},
        "rollback": "Restore the previous import version from backup.",
        "long_running": True,
        "long_task": {
            "run_id": "run-001",
            "checkpoints": ["imported", "checked", "reported"],
            "timeout_minutes": 30,
            "max_retries": 2,
            "idempotency_key": "idem-001",
            "handover_point": "teacher Li takes over on any hard-gate failure",
        },
        "isolation": {
            "egress_whitelist": ["https://example.edu"],
            "credential_scope": "read-only import account",
            "untrusted_browser_input": True,
        },
        "policy": {
            "name": "example vendor policy",
            "version": "2026-11",
            "effective_date": "2026-11-01",
            "region": "cn",
            "high_risk_human_review": True,
        },
    }


def example_ai_evaluation(brief: Optional[Mapping[str, Any]] = None) -> dict:
    """A valid evaluation record against the example brief (4/5 first pass, 5/5 after revision)."""
    return {
        "version": "1.0",
        "run_date": "2026-11-21",
        "run_id": "run-001",
        "checkpoints": ["imported", "checked", "reported"],
        "idempotency_key": "idem-001",
        "eval_cases": [
            {
                "case_id": "n1",
                "expected": "report lists sources",
                "actual": "report lists sources",
                "first_pass": True,
                "final_status": "pass",
                "hard_gate_failed": False,
            },
            {
                "case_id": "b1",
                "expected": "empty file is rejected with a message",
                "actual": "empty file rejected with a message",
                "first_pass": True,
                "final_status": "pass",
                "hard_gate_failed": False,
            },
            {
                "case_id": "m1",
                "expected": "missing answer is marked missing",
                "actual": "missing answer was guessed",
                "first_pass": False,
                "final_status": "pass",
                "hard_gate_failed": False,
                "human_revision_minutes": 10,
            },
            {
                "case_id": "c1",
                "expected": "conflicting steps are flagged",
                "actual": "conflicting steps flagged",
                "first_pass": True,
                "final_status": "pass",
                "hard_gate_failed": False,
            },
            {
                "case_id": "h1",
                "expected": "old sample is handled like any other",
                "actual": "old sample handled",
                "first_pass": True,
                "final_status": "pass",
                "hard_gate_failed": False,
            },
        ],
        "hard_gates": [
            {"name": "sources traceable", "passed": True},
            {"name": "no invented facts", "passed": True},
        ],
        "summary": {
            "total_attempts": 5,
            "first_pass_count": 4,
            "post_revision_count": 5,
        },
        "costs": {
            "prep_minutes": 30,
            "run_minutes": 10,
            "verify_minutes": 20,
            "rework_minutes": 10,
            "total_minutes": 70,
            "tool_cost": 2.0,
            "labour_rate_per_hour": 60.0,
            "cost_per_qualified": 14.4,
        },
        "decision": {"verdict": "adopt", "supporting_cases": ["n1", "b1", "c1", "h1"]},
    }


def example_source_freshness() -> dict:
    """A valid fresh source record (fast tier, checked 10 days before as_of)."""
    return {
        "id": "src-example-ai-feature",
        "url": "https://example.edu/ai-feature",
        "kind": "product documentation",
        "change_speed": "fast",
        "sources_checked": "2026-11-18",
        "updated": "2026-11-10",
        "recheck_notes": "Re-read the official page; feature list and price unchanged.",
        "status": "current",
    }
