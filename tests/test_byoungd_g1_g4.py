"""Tests for services/learner_evidence.py (byoungd/up G1-G4, pure functions).

No DB, no network, no LLM. Examples are synthetic; nothing from the
book's prose or English content is asserted here.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from services.learner_evidence import (
    example_ai_evaluation,
    example_ai_learning_log,
    example_ai_task_brief,
    example_evidence_chain,
    example_source_freshness,
    freshness_interval_days,
    verify_ai_evaluation,
    verify_ai_learning_log,
    verify_ai_task_brief,
    verify_evidence_chain,
    verify_source_freshness,
)


def _codes(result):
    return {i["code"] for i in result["issues"]}


def _gates(result):
    return {i["gate"] for i in result["issues"]}


# ── G1 · evidence chain ──────────────────────────────────────────────────


def test_g1_example_passes():
    result = verify_evidence_chain(example_evidence_chain())
    assert result["passed"], result["issues"]
    assert result["conflict"] is False
    assert result["samples_checked"] == 4


def test_g1_missing_transfer_fails():
    chain = example_evidence_chain()
    del chain["samples"]["transfer"]
    result = verify_evidence_chain(chain)
    assert not result["passed"]
    assert "missing_sample" in _codes(result)


def test_g1_baseline_with_tools_fails():
    chain = example_evidence_chain()
    chain["samples"]["baseline"]["tools_used"] = ["worked example"]
    result = verify_evidence_chain(chain)
    assert not result["passed"]
    assert "baseline_not_clean" in _codes(result)


def test_g1_delayed_without_delay_fails():
    chain = example_evidence_chain()
    chain["samples"]["delayed"]["delay_days"] = 0
    result = verify_evidence_chain(chain)
    assert not result["passed"]
    assert "bad_delay_days" in _codes(result)


def test_g1_delayed_prompts_not_removed_fails():
    chain = example_evidence_chain()
    chain["samples"]["delayed"]["prompts_removed"] = []
    result = verify_evidence_chain(chain)
    assert not result["passed"]
    assert "prompts_not_removed" in _codes(result)


def test_g1_transfer_bad_condition_fails():
    chain = example_evidence_chain()
    chain["samples"]["transfer"]["changed_condition"] = "mood"
    result = verify_evidence_chain(chain)
    assert not result["passed"]
    assert "bad_changed_condition" in _codes(result)


def test_g1_two_changes_in_one_round_fails():
    chain = example_evidence_chain()
    chain["samples"]["transfer"]["changed"] = ["audience", "time_limit"]
    result = verify_evidence_chain(chain)
    assert not result["passed"]
    assert "too_many_changes" in _codes(result)


def test_g1_statement_in_two_columns_fails():
    chain = example_evidence_chain()
    chain["statements"]["hypothesis"] = [chain["statements"]["fact"][0]]
    result = verify_evidence_chain(chain)
    assert not result["passed"]
    assert "statement_in_two_columns" in _codes(result)


def test_g1_conflict_continue_needs_acknowledgement():
    chain = example_evidence_chain()
    chain["samples"]["delayed"]["outcome"] = "fail"
    result = verify_evidence_chain(chain)
    assert result["conflict"] is True
    assert not result["passed"]
    assert "conflict_ignored" in _codes(result)
    chain["decision"]["conflict_acknowledged"] = True
    assert verify_evidence_chain(chain)["passed"]


def test_g1_ledger_without_gate_fails_and_stub_passes():
    chain = example_evidence_chain()
    chain["ledger"] = {"rows": [{"shot": 0, "source": "textbook p.12"}]}
    assert "ledger_gate_unavailable" in _codes(verify_evidence_chain(chain))

    def stub_ledger(spec):
        rows = spec.get("ledger", {}).get("rows")
        if isinstance(rows, list) and rows:
            return SimpleNamespace(passed=True, issues=[])
        return SimpleNamespace(
            passed=False, issues=[{"code": "empty_ledger", "message": "no rows"}]
        )

    assert verify_evidence_chain(chain, ledger_check=stub_ledger)["passed"]
    chain["ledger"] = {"rows": []}
    assert not verify_evidence_chain(chain, ledger_check=stub_ledger)["passed"]


# ── G2 · AI-learning log ─────────────────────────────────────────────────


def test_g2_example_passes_without_debt_or_miscalibration():
    result = verify_ai_learning_log(example_ai_learning_log())
    assert result["passed"], result["issues"]
    assert result["speed_debt"] is False
    assert result["miscalibrated"] is False
    assert "assisted" not in result["mastery_writable_samples"]


def test_g2_speed_debt_must_be_addressed():
    log = example_ai_learning_log()
    log["assisted"]["time_minutes"] = 10
    log["assisted"]["rework"] = 2
    result = verify_ai_learning_log(log)
    assert result["speed_debt"] is True
    assert not result["passed"]
    assert "speed_debt_unaddressed" in _codes(result)
    log["speed_debt_note"] = (
        "Faster, but the rework doubled; the scaffold did not stick."
    )
    assert verify_ai_learning_log(log)["passed"]


def test_g2_miscalibration_must_be_addressed():
    log = example_ai_learning_log()
    log["assisted"]["accuracy"] = 0.4
    result = verify_ai_learning_log(log)
    assert result["miscalibrated"] is True
    assert not result["passed"]
    assert "miscalibration_unaddressed" in _codes(result)
    log["calibration_note"] = (
        "Confidence rose while accuracy fell; recalibrate before more tool use."
    )
    assert verify_ai_learning_log(log)["passed"]


def test_g2_baseline_with_ai_fails():
    log = example_ai_learning_log()
    log["baseline"]["ai_used"] = True
    result = verify_ai_learning_log(log)
    assert not result["passed"]
    assert "baseline_not_clean" in _codes(result)


def test_g2_final_judgement_must_be_forbidden():
    log = example_ai_learning_log()
    log["ai_scope"]["forbidden_actions"] = ["write the full answer"]
    result = verify_ai_learning_log(log)
    assert not result["passed"]
    assert "final_judgement_not_forbidden" in _codes(result)


def test_g2_assisted_score_must_not_count_toward_mastery():
    log = example_ai_learning_log()
    log["assisted"]["counts_toward_mastery"] = True
    result = verify_ai_learning_log(log)
    assert not result["passed"]
    assert "mastery_contaminated" in _codes(result)


def test_g2_mastery_write_source_must_not_be_ai_assisted():
    log = example_ai_learning_log()
    log["mastery_write"] = {"source": "ai_assisted"}
    assert "bad_mastery_source" in _codes(verify_ai_learning_log(log))
    log["mastery_write"] = {"source": "bkt"}
    assert verify_ai_learning_log(log)["passed"]


def test_g2_delayed_window_is_3_to_7_days():
    log = example_ai_learning_log()
    log["delayed_independent"]["delay_days"] = 2
    assert "bad_delay_days" in _codes(verify_ai_learning_log(log))
    log["delayed_independent"]["delay_days"] = 7
    assert verify_ai_learning_log(log)["passed"]


# ── G3 · task brief + evaluation ─────────────────────────────────────────


def test_g3_brief_and_evaluation_pass():
    brief = example_ai_task_brief()
    assert verify_ai_task_brief(brief)["passed"]
    record = example_ai_evaluation(brief)
    result = verify_ai_evaluation(record, brief)
    assert result["passed"], result["issues"]
    assert result["first_pass_rate"] == pytest.approx(0.8)
    assert result["post_revision_rate"] == pytest.approx(1.0)
    assert result["total_minutes"] == pytest.approx(70.0)
    assert result["cost_per_qualified"] == pytest.approx(14.4)


def test_g3_brief_missing_case_kind_fails():
    brief = example_ai_task_brief()
    brief["eval_set"]["cases"] = [
        c for c in brief["eval_set"]["cases"] if c["kind"] != "boundary"
    ]
    result = verify_ai_task_brief(brief)
    assert not result["passed"]
    assert "missing_case_kind" in _codes(result)


def test_g3_brief_missing_human_gate_fails():
    brief = example_ai_task_brief()
    brief["human_gates"] = [g for g in brief["human_gates"] if g["gate"] != "cost"]
    result = verify_ai_task_brief(brief)
    assert not result["passed"]
    assert "missing_human_gate" in _codes(result)


def test_g3_brief_long_running_without_recovery_fails():
    brief = example_ai_task_brief()
    del brief["long_task"]
    result = verify_ai_task_brief(brief)
    assert not result["passed"]
    assert "missing_long_task" in _codes(result)


def test_g3_brief_policy_without_high_risk_review_fails():
    brief = example_ai_task_brief()
    del brief["policy"]["high_risk_human_review"]
    result = verify_ai_task_brief(brief)
    assert not result["passed"]
    assert "missing_high_risk_review" in _codes(result)


def test_g3_evaluation_before_freeze_fails():
    brief = example_ai_task_brief()
    record = example_ai_evaluation(brief)
    record["run_date"] = "2026-11-19"
    result = verify_ai_evaluation(record, brief)
    assert not result["passed"]
    assert "ran_before_freeze" in _codes(result)


def test_g3_evaluation_wrong_eval_set_fails():
    brief = example_ai_task_brief()
    record = example_ai_evaluation(brief)
    record["eval_cases"] = record["eval_cases"][:4]
    record["summary"] = {
        "total_attempts": 4,
        "first_pass_count": 3,
        "post_revision_count": 4,
    }
    result = verify_ai_evaluation(record, brief)
    assert not result["passed"]
    assert "eval_set_mismatch" in _codes(result)


def test_g3_hard_gate_failure_blocks_adopt():
    brief = example_ai_task_brief()
    record = example_ai_evaluation(brief)
    record["hard_gates"][0]["passed"] = False
    result = verify_ai_evaluation(record, brief)
    assert not result["passed"]
    assert "hard_gate_failed" in _codes(result)
    assert "adopt_with_failed_gate" in _codes(result)


def test_g3_rates_are_recomputed_not_trusted():
    brief = example_ai_task_brief()
    record = example_ai_evaluation(brief)
    record["summary"]["first_pass_count"] = 5
    result = verify_ai_evaluation(record, brief)
    assert not result["passed"]
    assert "first_pass_mismatch" in _codes(result)


def test_g3_cost_must_add_up_and_zero_qualified_is_not_computable():
    brief = example_ai_task_brief()
    record = example_ai_evaluation(brief)
    record["costs"]["total_minutes"] = 60
    result = verify_ai_evaluation(record, brief)
    assert not result["passed"]
    assert "total_minutes_mismatch" in _codes(result)

    record = example_ai_evaluation(brief)
    for case in record["eval_cases"]:
        case["final_status"] = "fail"
        case["first_pass"] = False
    record["summary"] = {
        "total_attempts": 5,
        "first_pass_count": 0,
        "post_revision_count": 0,
    }
    record["costs"]["cost_per_qualified"] = 0
    record["decision"] = {"verdict": "fix_and_retest", "supporting_cases": ["m1"]}
    result = verify_ai_evaluation(record, brief)
    assert not result["passed"]
    assert "zero_qualified_cost" in _codes(result)
    record["costs"]["cost_per_qualified"] = "not_computable"
    result = verify_ai_evaluation(record, brief)
    assert result["passed"], result["issues"]
    assert result["cost_per_qualified"] == "not_computable"


def test_g3_decision_needs_supporting_cases():
    brief = example_ai_task_brief()
    record = example_ai_evaluation(brief)
    record["decision"]["supporting_cases"] = []
    result = verify_ai_evaluation(record, brief)
    assert not result["passed"]
    assert "missing_supporting_cases" in _codes(result)


# ── G4 · source freshness ────────────────────────────────────────────────


def test_g4_example_is_fresh():
    result = verify_source_freshness(example_source_freshness(), as_of="2026-11-28")
    assert result["passed"], result["issues"]
    assert result["interval_days"] == 30
    assert result["age_days"] == 10
    assert result["due_date"] == "2026-12-18"
    assert result["counts_as_current_evidence"] is True


def test_g4_overdue_current_source_fails_but_historical_passes():
    source = example_source_freshness()
    result = verify_source_freshness(source, as_of="2027-01-01")
    assert not result["passed"]
    assert "overdue_recheck" in _codes(result)
    source["status"] = "historical"
    result = verify_source_freshness(source, as_of="2027-01-01")
    assert result["passed"], result["issues"]
    assert result["counts_as_current_evidence"] is False


def test_g4_checked_before_last_edit_is_stale():
    source = example_source_freshness()
    source["sources_checked"] = "2026-11-01"
    result = verify_source_freshness(source, as_of="2026-11-28")
    assert not result["passed"]
    assert "stale_verification" in _codes(result)


def test_g4_recheck_needs_notes():
    source = example_source_freshness()
    del source["recheck_notes"]
    result = verify_source_freshness(source, as_of="2026-11-28")
    assert not result["passed"]
    assert "missing_recheck_notes" in _codes(result)


def test_g4_date_bump_without_recheck_fails():
    source = example_source_freshness()
    previous = copy.deepcopy(source)
    source["updated"] = "2026-11-20"
    result = verify_source_freshness(source, as_of="2026-11-28", previous=previous)
    assert not result["passed"]
    assert "date_bumped_without_recheck" in _codes(result)
    source["sources_checked"] = "2026-11-20"
    source["recheck_notes"] = "Re-read after the update; content unchanged."
    assert verify_source_freshness(source, as_of="2026-11-28", previous=previous)[
        "passed"
    ]


def test_g4_historical_does_not_count_as_current_when_required():
    source = example_source_freshness()
    source["status"] = "historical"
    result = verify_source_freshness(source, as_of="2026-11-28", require_current=True)
    assert not result["passed"]
    assert "historical_not_current" in _codes(result)


def test_g4_intervals():
    assert freshness_interval_days("fast") == 30
    assert freshness_interval_days("medium") == 60
    assert freshness_interval_days("slow") == 120
    with pytest.raises(ValueError):
        freshness_interval_days("frozen")
