"""Tests for the narration source ledger gate (G1 graft). Pure functions."""

import copy

from services.narration_source_ledger import (
    AdversarialReview,
    LedgerAlternative,
    LedgerEvidence,
    LedgerRow,
    SourceLedger,
    SourceTier,
    attach_ledger,
    certify_lesson_script,
    ledger_from_dict,
    ledger_to_dict,
    verify_lesson_source_ledger,
    verify_source_ledger,
)
from services.provenance import ProvenanceLabel
from services.video_lesson import triangle_angle_sum_spec


def _review(**overrides):
    checks = {
        "no_unsourced_assertions": True,
        "every_row_tiered": True,
        "disputes_listed_both_sides": True,
        "quotes_present": True,
    }
    checks.update(overrides.pop("checks", {}))
    return {"reviewer": "adversarial", "checks": checks, **overrides}


def _row(row_id="L01", **overrides):
    base = {
        "id": row_id,
        "claim": "三角形三个内角的和是 180 度",
        "shot": 2,
        "label": "material",
        "evidence": [
            {"source": "人教版数学七年级下册", "tier": "T1", "quote": "三角形三个内角的和等于 180 度。"}
        ],
        "status": "single-source",
    }
    base.update(overrides)
    return base


def _ledger(rows=None, **overrides):
    base = {"rows": rows if rows is not None else [_row()], "review": _review()}
    base.update(overrides)
    return base


def _codes(check):
    return [issue.code for issue in check.issues]


def test_valid_ledger_passes():
    rows = [
        _row("L01", shot=0, label="generated", evidence=[], status="framing",
             claim="看这个三角形，把三个角标出来，准备拼在一起。"),
        _row("L02", shot=1, label="generated", evidence=[], status="framing",
             claim="把三个角拼到一条直线上，看拼出的角是不是平角。"),
        _row("L03", shot=1, label="supplement", status="disputed",
             claim="拼出的角是平角",
             evidence=[{"source": "人教版数学七年级下册", "tier": "T2", "quote": "平角是 180 度的角。"}],
             alternative={"claim": "拼出的角不是平角", "source": "课堂讨论记录",
                          "tier": "T3", "quote": "有学生认为中间留了空隙。"}),
        _row("L04", shot=2),
    ]
    check = verify_source_ledger(_ledger(rows), scene_count=3, factual_shots=[0, 1, 2])
    assert check.passed, _codes(check)
    assert check.rows_checked == 4


def test_missing_ledger_fails_adapter_fail_closed():
    spec = triangle_angle_sum_spec()
    assert "source_ledger" not in spec
    result = certify_lesson_script(spec, set())
    assert result["passed"] is False
    assert result["video_lesson"]["passed"] is True
    assert result["source_ledger"]["passed"] is False
    assert any(i["code"] == "missing_ledger" for i in result["source_ledger"]["issues"])


def test_empty_rows_and_non_list_rows_fail():
    assert "empty_ledger" in _codes(verify_source_ledger(_ledger([]), scene_count=3))
    assert "empty_ledger" in _codes(verify_source_ledger(_ledger({"rows": "nope"}), scene_count=3))
    assert "not_an_object" in _codes(verify_source_ledger(["not", "a", "dict"], scene_count=3))
    assert "bad_scene_count" in _codes(verify_source_ledger(_ledger(), scene_count=0))


def test_bad_and_duplicate_row_ids_fail():
    check = verify_source_ledger(_ledger([_row("X1")]), scene_count=3)
    assert "bad_row_id" in _codes(check)
    check = verify_source_ledger(_ledger([_row("L01"), _row("L01", shot=1)]), scene_count=3)
    assert "duplicate_row_id" in _codes(check)


def test_empty_and_overlong_claims_fail():
    assert "empty_claim" in _codes(verify_source_ledger(_ledger([_row(claim="  ")]), scene_count=3))
    assert "claim_too_long" in _codes(
        verify_source_ledger(_ledger([_row(claim="断" * 121)]), scene_count=3)
    )


def test_dangling_and_non_integer_shots_fail():
    assert "dangling_shot" in _codes(verify_source_ledger(_ledger([_row(shot=3)]), scene_count=3))
    assert "dangling_shot" in _codes(verify_source_ledger(_ledger([_row(shot=-1)]), scene_count=3))
    assert "bad_shot" in _codes(verify_source_ledger(_ledger([_row(shot=True)]), scene_count=3))
    assert "bad_shot" in _codes(verify_source_ledger(_ledger([_row(shot="2")]), scene_count=3))


def test_material_supplement_generated_evidence_rules():
    no_evidence = _row(evidence=[])
    assert "missing_evidence" in _codes(verify_source_ledger(_ledger([no_evidence]), scene_count=3))
    t3_only = _row(evidence=[{"source": "某论坛帖子", "tier": "T3", "quote": "都说内角和是 180 度。"}])
    codes = _codes(verify_source_ledger(_ledger([t3_only]), scene_count=3))
    assert "t3_only_unsupported" in codes
    assert "material_needs_strong_source" in codes
    supplement_bare = _row(label="supplement", evidence=[])
    assert "missing_evidence" in _codes(
        verify_source_ledger(_ledger([supplement_bare]), scene_count=3)
    )
    generated_cited = _row(label="generated", status="framing",
                           evidence=[{"source": "某书", "tier": "T1", "quote": "引文。"}])
    codes = _codes(verify_source_ledger(_ledger([generated_cited]), scene_count=3))
    assert "generated_must_not_cite" in codes
    generated_wrong_status = _row(label="generated", evidence=[], status="single-source")
    assert "generated_needs_framing_status" in _codes(
        verify_source_ledger(_ledger([generated_wrong_status]), scene_count=3)
    )
    sourced_framing = _row(status="framing")
    assert "framing_status_needs_generated" in _codes(
        verify_source_ledger(_ledger([sourced_framing]), scene_count=3)
    )


def test_evidence_entry_rules():
    assert "missing_quote" in _codes(
        verify_source_ledger(
            _ledger([_row(evidence=[{"source": "某书", "tier": "T1", "quote": "  "}])]),
            scene_count=3,
        )
    )
    assert "empty_source" in _codes(
        verify_source_ledger(
            _ledger([_row(evidence=[{"source": "", "tier": "T1", "quote": "引文。"}])]),
            scene_count=3,
        )
    )
    assert "bad_tier" in _codes(
        verify_source_ledger(
            _ledger([_row(evidence=[{"source": "某书", "tier": "T9", "quote": "引文。"}])]),
            scene_count=3,
        )
    )
    assert "quote_too_long" in _codes(
        verify_source_ledger(
            _ledger([_row(evidence=[{"source": "某书", "tier": "T1", "quote": "引" * 401}])]),
            scene_count=3,
        )
    )
    assert "bad_evidence" in _codes(
        verify_source_ledger(_ledger([_row(evidence="not-a-list")]), scene_count=3)
    )
    assert "bad_label" in _codes(verify_source_ledger(_ledger([_row(label="bogus")]), scene_count=3))


def test_dispute_rules():
    disputed_bare = _row(status="disputed")
    assert "dispute_incomplete" in _codes(
        verify_source_ledger(_ledger([disputed_bare]), scene_count=3)
    )
    disputed_partial = _row(
        status="disputed",
        alternative={"claim": "另一说", "source": "某记录", "tier": "T2", "quote": ""},
    )
    assert "dispute_incomplete" in _codes(
        verify_source_ledger(_ledger([disputed_partial]), scene_count=3)
    )
    alternative_without_dispute = _row(
        alternative={"claim": "另一说", "source": "某记录", "tier": "T2", "quote": "摘录。"}
    )
    assert "alternative_without_dispute" in _codes(
        verify_source_ledger(_ledger([alternative_without_dispute]), scene_count=3)
    )


def test_status_evidence_mismatch():
    verified_single_t2 = _row(
        status="verified",
        evidence=[{"source": "某教辅", "tier": "T2", "quote": "内角和等于 180 度。"}],
    )
    assert "status_evidence_mismatch" in _codes(
        verify_source_ledger(_ledger([verified_single_t2]), scene_count=3)
    )
    single_source_two = _row(
        status="single-source",
        evidence=[
            {"source": "教材", "tier": "T1", "quote": "内角和等于 180 度。"},
            {"source": "教辅", "tier": "T2", "quote": "内角和等于 180 度。"},
        ],
    )
    assert "status_evidence_mismatch" in _codes(
        verify_source_ledger(_ledger([single_source_two]), scene_count=3)
    )
    verified_two_t2 = _row(
        status="verified",
        evidence=[
            {"source": "教辅甲", "tier": "T2", "quote": "内角和等于 180 度。"},
            {"source": "教辅乙", "tier": "T2", "quote": "三角形内角之和为 180 度。"},
        ],
    )
    assert verify_source_ledger(_ledger([verified_two_t2]), scene_count=3).passed


def test_duplicate_assertion_same_shot_fails_other_shot_passes():
    rows = [_row("L01", shot=2), _row("L02", shot=2)]
    assert "duplicate_assertion" in _codes(verify_source_ledger(_ledger(rows), scene_count=3))
    rows = [_row("L01", shot=1), _row("L02", shot=2)]
    assert verify_source_ledger(_ledger(rows), scene_count=3).passed


def test_review_record_rules():
    assert "missing_review" in _codes(verify_source_ledger({"rows": [_row()]}, scene_count=3))
    assert "bad_reviewer" in _codes(
        verify_source_ledger(_ledger(review={"reviewer": " ", "checks": _review()["checks"]}), scene_count=3)
    )
    assert "review_check_failed" in _codes(
        verify_source_ledger(
            _ledger(review=_review(checks={"quotes_present": False})), scene_count=3
        )
    )
    assert "review_check_missing" in _codes(
        verify_source_ledger(
            _ledger(review={"reviewer": "adversarial", "checks": {"no_unsourced_assertions": True}}),
            scene_count=3,
        )
    )
    assert "bad_notes" in _codes(
        verify_source_ledger(_ledger(review=_review(notes=42)), scene_count=3)
    )


def test_coverage_factual_shots():
    rows = [_row(shot=2)]
    check = verify_source_ledger(_ledger(rows), scene_count=3, factual_shots=[0, 1, 2])
    assert "shot_uncovered" in _codes(check)
    assert verify_source_ledger(_ledger(rows), scene_count=3).passed
    assert "bad_factual_shot" in _codes(
        verify_source_ledger(_ledger(rows), scene_count=3, factual_shots=[9])
    )


def test_bad_as_of_and_too_many_rows():
    assert "bad_as_of" in _codes(verify_source_ledger(_ledger(as_of="2026/11/5"), scene_count=3))
    assert verify_source_ledger(_ledger(as_of="2026-11-05"), scene_count=3).passed
    rows = [_row(f"L{i:03d}", shot=i % 3, claim=f"断言{i}") for i in range(201)]
    assert "too_many_rows" in _codes(verify_source_ledger(_ledger(rows), scene_count=3))


def test_certify_combined_video_and_ledger():
    spec = triangle_angle_sum_spec()
    spec["verified"] = True
    result = certify_lesson_script(spec, set())
    assert result["passed"] is False
    assert result["video_lesson"]["passed"] is False
    assert result["source_ledger"]["passed"] is False


def test_dataclass_round_trip_and_attach_ledger():
    ledger = SourceLedger(
        rows=[
            LedgerRow(
                id="L01",
                claim="三角形三个内角的和是 180 度",
                shot=2,
                label=ProvenanceLabel.MATERIAL,
                evidence=[
                    LedgerEvidence(source="人教版数学七年级下册", tier=SourceTier.T1,
                                   quote="三角形三个内角的和等于 180 度。")
                ],
                status="single-source",
            ),
            LedgerRow(
                id="L02",
                claim="把三个角拼到一条直线上",
                shot=1,
                label=ProvenanceLabel.GENERATED,
                status="framing",
            ),
            LedgerRow(
                id="L03",
                claim="看这个三角形，把三个角标出来",
                shot=0,
                label=ProvenanceLabel.GENERATED,
                status="framing",
            ),
        ],
        review=AdversarialReview(
            reviewer="adversarial",
            checks={key: True for key in
                    ("no_unsourced_assertions", "every_row_tiered",
                     "disputes_listed_both_sides", "quotes_present")},
        ),
        as_of="2026-11-05",
    )
    data = ledger_to_dict(ledger)
    assert ledger_from_dict(data) == ledger
    spec = triangle_angle_sum_spec()
    attached = attach_ledger(spec, ledger)
    assert "source_ledger" not in spec
    assert attached["source_ledger"]["rows"][0]["label"] == "material"
    check = verify_lesson_source_ledger(attached)
    assert check.passed, [i.to_dict() for i in check.issues]


def test_disputed_row_with_alternative_dataclass():
    ledger = SourceLedger(
        rows=[
            LedgerRow(
                id="L01",
                claim="拼出的角是平角",
                shot=1,
                label=ProvenanceLabel.SUPPLEMENT,
                evidence=[LedgerEvidence(source="教辅", tier=SourceTier.T2,
                                         quote="平角是 180 度的角。")],
                status="disputed",
                alternative=LedgerAlternative(
                    claim="拼出的角不是平角", source="课堂讨论记录",
                    tier=SourceTier.T3, quote="有学生认为中间留了空隙。",
                ),
            )
        ],
        review=AdversarialReview(
            reviewer="adversarial",
            checks={key: True for key in
                    ("no_unsourced_assertions", "every_row_tiered",
                     "disputes_listed_both_sides", "quotes_present")},
        ),
    )
    check = verify_source_ledger(ledger_to_dict(ledger), scene_count=3)
    assert check.passed, [i.to_dict() for i in check.issues]


def test_attach_ledger_does_not_mutate_input():
    spec = triangle_angle_sum_spec()
    snapshot = copy.deepcopy(spec)
    ledger = SourceLedger(
        rows=[LedgerRow(id="L01", claim="三角形三个内角的和是 180 度", shot=2,
                        label=ProvenanceLabel.MATERIAL,
                        evidence=[LedgerEvidence(source="教材", tier=SourceTier.T1,
                                                 quote="内角和等于 180 度。")])],
        review=AdversarialReview(reviewer="adversarial", checks={
            "no_unsourced_assertions": True, "every_row_tiered": True,
            "disputes_listed_both_sides": True, "quotes_present": True}),
    )
    attach_ledger(spec, ledger)
    assert spec == snapshot
