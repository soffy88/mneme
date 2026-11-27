"""Tests for services/physics_contracts.py (AI Physics Assistant G1-G4).

Pure functions: no DB, no network, no LLM. No content from the audited
site is used anywhere: fixtures are Mneme-written toy values (a
projectile-motion question, synthetic counts), never site text.
"""

from __future__ import annotations


from services.physics_contracts import (
    aggregate_common_errors,
    compute_mastery_snapshot,
    dedup_key_for_row,
    resolve_weak_roots_kind,
    verify_import_batch,
    verify_physics_content_admission,
    weak_roots_namespace,
)

KU = "ku-projectile"
TB = "tb-renjiao-physics-bx1"
KNOWN_KU = {KU, "ku-pendulum"}
KNOWN_TB = {TB}


def _ledger():
    return {
        "rows": [
            {
                "id": "L01",
                "claim": "Projectile horizontal motion is uniform.",
                "shot": 0,
                "label": "material",
                "evidence": [
                    {
                        "source": "Renjiao physics textbook, chapter 5",
                        "tier": "T1",
                        "quote": "Horizontal motion is uniform linear motion.",
                    }
                ],
                "status": "verified",
            }
        ],
        "review": {
            "reviewer": "reviewer",
            "checks": {
                "no_unsourced_assertions": True,
                "every_row_tiered": True,
                "disputes_listed_both_sides": True,
                "quotes_present": True,
            },
        },
    }


def _spec(**overrides):
    spec = {
        "ku_id": KU,
        "stem": "A ball is thrown horizontally. Which statement is true?",
        "question_type": "single_choice",
        "options": {"A": "It speeds up horizontally.", "B": "It moves uniformly."},
        "refs": [{"kind": "ku", "id": KU}, {"kind": "textbook", "id": TB}],
        "formulas": [{"text": "x = v0 * t"}],
        "images": [{"role": "stem_figure", "status": "ok"}],
        "answer": {"value": "B"},
        "source_ledger": _ledger(),
        "curriculum_mapping": {
            "textbook_id": TB,
            "chapter": "5",
            "standard_id": "std-phy-5",
            "reviewed_by": "reviewer",
        },
        "knowledge_label": {"ku_id": KU, "reviewed_by": "reviewer"},
    }
    spec.update(overrides)
    return spec


def _codes(result):
    return {i["code"] for i in result["issues"]}


# ── G1 ───────────────────────────────────────────────────────────────────


def test_g1_valid_question_passes():
    result = verify_physics_content_admission(
        _spec(), known_ku_ids=KNOWN_KU, known_textbook_ids=KNOWN_TB
    )
    assert result["passed"] is True
    assert result["gates"] == {
        "ledger": "pass",
        "citations": "pass",
        "curriculum": "pass",
        "formulas": "pass",
        "figures": "pass",
        "atlas": "not_applicable",
        "labels": "pass",
    }


def test_g1_missing_ledger_fails():
    spec = _spec()
    del spec["source_ledger"]
    result = verify_physics_content_admission(
        spec, known_ku_ids=KNOWN_KU, known_textbook_ids=KNOWN_TB
    )
    assert result["passed"] is False
    assert result["gates"]["ledger"] == "fail"
    assert "missing_ledger" in _codes(result)


def test_g1_unknown_ku_reference_fails():
    spec = _spec(refs=[{"kind": "ku", "id": "ku-nope"}])
    result = verify_physics_content_admission(
        spec, known_ku_ids=KNOWN_KU, known_textbook_ids=KNOWN_TB
    )
    assert result["passed"] is False
    assert result["gates"]["citations"] == "fail"
    assert "unknown_ku" in _codes(result)


def test_g1_image_only_formula_fails():
    spec = _spec(formulas=[{"image_only": True}])
    result = verify_physics_content_admission(
        spec, known_ku_ids=KNOWN_KU, known_textbook_ids=KNOWN_TB
    )
    assert result["passed"] is False
    assert "image_only_formula" in _codes(result)


def test_g1_leaked_html_entity_in_stem_fails():
    spec = _spec(stem="Compare $W_{1}&gt;W_{2}$ for the two cases.")
    result = verify_physics_content_admission(
        spec, known_ku_ids=KNOWN_KU, known_textbook_ids=KNOWN_TB
    )
    assert result["passed"] is False
    assert "unrendered_markup" in _codes(result)


def test_g1_missing_figure_fails():
    spec = _spec(stem="如图, the ball follows which path?", images=None)
    result = verify_physics_content_admission(
        spec, known_ku_ids=KNOWN_KU, known_textbook_ids=KNOWN_TB
    )
    assert result["passed"] is False
    assert "missing_figure" in _codes(result)
    spec = _spec(images=[{"role": "stem_figure", "status": "failed"}])
    result = verify_physics_content_admission(
        spec, known_ku_ids=KNOWN_KU, known_textbook_ids=KNOWN_TB
    )
    assert "missing_figure" in _codes(result)


def test_g1_calculation_without_recompute_fails_then_atlas_passes():
    base = _spec(question_type="calculation", answer={"value": "100 W"})
    result = verify_physics_content_admission(
        base, known_ku_ids=KNOWN_KU, known_textbook_ids=KNOWN_TB
    )
    assert result["passed"] is False
    assert "not_recomputed" in _codes(result)
    atlas = _spec(
        question_type="calculation",
        answer={
            "value": "100 W",
            "recomputed": True,
            "recompute_method": "atlas_model",
            "model_ref": "projectile_motion",
        },
    )
    result = verify_physics_content_admission(
        atlas, known_ku_ids=KNOWN_KU, known_textbook_ids=KNOWN_TB
    )
    assert result["passed"] is True
    assert result["gates"]["atlas"] == "pass"
    unknown_model = _spec(
        question_type="calculation",
        answer={
            "value": "100 W",
            "recomputed": True,
            "recompute_method": "atlas_model",
            "model_ref": "not_a_model",
        },
    )
    result = verify_physics_content_admission(
        unknown_model, known_ku_ids=KNOWN_KU, known_textbook_ids=KNOWN_TB
    )
    assert "unknown_atlas_model" in _codes(result)
    independent = _spec(
        question_type="calculation",
        answer={
            "value": "100 W",
            "recomputed": True,
            "recompute_method": "independent_recompute",
            "recompute_evidence": "energy method: mgh/t = 100 W",
        },
    )
    result = verify_physics_content_admission(
        independent, known_ku_ids=KNOWN_KU, known_textbook_ids=KNOWN_TB
    )
    assert result["passed"] is True


def test_g1_mislabelled_knowledge_point_fails():
    spec = _spec(knowledge_label={"ku_id": "ku-pendulum", "reviewed_by": "reviewer"})
    result = verify_physics_content_admission(
        spec, known_ku_ids=KNOWN_KU, known_textbook_ids=KNOWN_TB
    )
    assert result["passed"] is False
    assert "label_mismatch" in _codes(result)
    spec = _spec(knowledge_label={"ku_id": KU, "reviewed_by": ""})
    result = verify_physics_content_admission(
        spec, known_ku_ids=KNOWN_KU, known_textbook_ids=KNOWN_TB
    )
    assert "missing_label_reviewer" in _codes(result)


def test_g1_curriculum_without_human_review_fails():
    mapping = {
        "textbook_id": TB,
        "chapter": "5",
        "standard_id": "std-phy-5",
        "reviewed_by": "",
    }
    spec = _spec(curriculum_mapping=mapping)
    result = verify_physics_content_admission(
        spec, known_ku_ids=KNOWN_KU, known_textbook_ids=KNOWN_TB
    )
    assert result["passed"] is False
    assert "missing_human_review" in _codes(result)


# ── G2 ───────────────────────────────────────────────────────────────────


def _snapshot(**overrides):
    kwargs = {
        "correct": 3,
        "total": 10,
        "p_mastery": 0.5,
        "evidence_n": 10,
        "mastery_confirmed": False,
        "mastery_source": "bkt",
        "mastery_method": "BKT p(L) update, slip 0.1, guess 0.2",
    }
    kwargs.update(overrides)
    return compute_mastery_snapshot(**kwargs)


def test_g2_mastery_and_accuracy_reported_separately():
    result = _snapshot()
    assert result["passed"] is True
    assert result["status"] == "weak"
    assert result["accuracy"] == 0.3
    assert result["mastery_p"] == 0.5
    assert result["weak_below"] == 0.6
    assert result["mastered_at"] == 0.7


def test_g2_mastered_needs_gate_confirmation():
    result = _snapshot(p_mastery=0.8, mastery_confirmed=False)
    assert result["status"] == "estimated_mastered"
    result = _snapshot(p_mastery=0.8, mastery_confirmed=True)
    assert result["status"] == "mastered"
    result = _snapshot(p_mastery=0.65)
    assert result["status"] == "developing"


def test_g2_direct_accuracy_as_mastery_fails():
    result = _snapshot(mastery_source="direct_accuracy")
    assert result["passed"] is False
    assert "mastery_must_not_be_accuracy" in _codes(result)


def test_g2_thin_evidence_publishes_no_label():
    result = _snapshot(evidence_n=3)
    assert result["passed"] is False
    assert result["status"] == "insufficient_evidence"
    assert "insufficient_evidence" in _codes(result)


def test_g2_missing_method_fails():
    result = _snapshot(mastery_method="")
    assert result["passed"] is False
    assert "missing_mastery_method" in _codes(result)


def test_g2_weak_roots_kinds_are_namespaced():
    assert weak_roots_namespace("cognitive_mastery") == "cognitive:weak_roots"
    assert weak_roots_namespace("prereq_diagnosis") == "prereq:weak_roots"
    assert weak_roots_namespace("other") is None
    resolved = resolve_weak_roots_kind({"kind": "cognitive_mastery"})
    assert resolved["passed"] is True
    assert resolved["source"] == "cognitive_service.weakness_roots"
    assert resolve_weak_roots_kind({"kind": "mystery"})["passed"] is False
    assert resolve_weak_roots_kind({})["passed"] is False


# ── G3 ───────────────────────────────────────────────────────────────────


def _record(qid, attempted, wrong, category="concept_confusion"):
    return {
        "question_id": qid,
        "n_attempted": attempted,
        "n_wrong": wrong,
        "error_rate": wrong / attempted,
        "typical_errors": [
            {"category": category, "description": "mixed up the two concepts"}
        ],
    }


def test_g3_publishable_sorted_by_error_rate():
    records = [_record("q-low", 20, 10), _record("q-high", 10, 8)]
    result = aggregate_common_errors(records)
    assert result["passed"] is True
    assert [r["question_id"] for r in result["publishable"]] == ["q-high", "q-low"]
    assert result["publishable"][0]["error_rate"] == 0.8
    assert result["publishable"][0]["n_attempted"] == 10
    assert result["publishable"][0]["n_wrong"] == 8


def test_g3_rate_mismatch_fails():
    record = _record("q-x", 10, 5)
    record["error_rate"] = 0.9
    result = aggregate_common_errors([record])
    assert result["passed"] is False
    assert "rate_mismatch" in _codes(result)


def test_g3_small_sample_withheld_not_published():
    result = aggregate_common_errors([_record("q-tiny", 4, 4)])
    assert result["passed"] is True
    assert result["publishable"] == []
    assert result["withheld_count"] == 1
    assert result["suppressed"][0]["reason"] == "sample_too_small"


def test_g3_identifiable_student_data_fails():
    record = _record("q-x", 10, 5)
    record["student_name"] = "Liu Yang"
    result = aggregate_common_errors([record])
    assert result["passed"] is False
    assert "identifiable_student" in _codes(result)


def test_g3_unknown_error_category_fails():
    record = _record("q-x", 10, 5, category="careless")
    result = aggregate_common_errors([record])
    assert result["passed"] is False
    assert "unknown_error_category" in _codes(result)


# ── G4 ───────────────────────────────────────────────────────────────────


def _question_row(**overrides):
    row = {
        "stem": "A ball is thrown horizontally.",
        "question_type": "single_choice",
        "options_a": "A",
        "options_b": "B",
        "options_c": "C",
        "options_d": "D",
        "answer": "B",
        "difficulty": 2,
        "paper": "Mock 1",
        "chapter": "5",
        "knowledge_points": "projectile motion",
        "kp_ids": KU,
    }
    row.update(overrides)
    return row


def test_g4_valid_question_batch_passes():
    batch = {"import_type": "question", "rows": [_question_row()]}
    result = verify_import_batch(
        batch, known_ku_ids=KNOWN_KU, existing_dedup_keys=set()
    )
    assert result["passed"] is True
    assert result["rows_checked"] == 1
    assert result["row_errors"] == []


def test_g4_duplicate_keys_fail():
    batch = {"import_type": "question", "rows": [_question_row(), _question_row()]}
    result = verify_import_batch(
        batch, known_ku_ids=KNOWN_KU, existing_dedup_keys=set()
    )
    assert result["passed"] is False
    assert any(
        e["code"] == "duplicate_in_batch"
        for row in result["row_errors"]
        for e in row["errors"]
    )
    existing = {dedup_key_for_row("question", _question_row())}
    batch = {"import_type": "question", "rows": [_question_row()]}
    result = verify_import_batch(
        batch, known_ku_ids=KNOWN_KU, existing_dedup_keys=existing
    )
    assert any(
        e["code"] == "duplicate_of_existing"
        for row in result["row_errors"]
        for e in row["errors"]
    )


def test_g4_unknown_kp_and_missing_dedup_set_fail():
    row = _question_row(kp_ids="ku-nope")
    batch = {"import_type": "question", "rows": [row]}
    result = verify_import_batch(
        batch, known_ku_ids=KNOWN_KU, existing_dedup_keys=set()
    )
    assert result["passed"] is False
    assert any(
        e["code"] == "unknown_kp" for row in result["row_errors"] for e in row["errors"]
    )
    result = verify_import_batch(batch, known_ku_ids=KNOWN_KU)
    assert "dedup_set_missing" in _codes(result)


def test_g4_fuzzy_match_needs_human_reviewer():
    row = _question_row(kp_match="fuzzy")
    batch = {"import_type": "question", "rows": [row]}
    result = verify_import_batch(
        batch, known_ku_ids=KNOWN_KU, existing_dedup_keys=set()
    )
    assert result["passed"] is False
    assert any(
        e["code"] == "fuzzy_unreviewed"
        for row in result["row_errors"]
        for e in row["errors"]
    )
    row = _question_row(kp_match="fuzzy", kp_reviewed_by="reviewer")
    batch = {"import_type": "question", "rows": [row]}
    result = verify_import_batch(
        batch, known_ku_ids=KNOWN_KU, existing_dedup_keys=set()
    )
    assert result["passed"] is True


def test_g4_student_import_off_by_default():
    batch = {
        "import_type": "student",
        "rows": [
            {
                "student_name": "Test",
                "student_no": "S1",
                "grade": "10",
                "class_name": "1",
            }
        ],
    }
    result = verify_import_batch(
        batch, known_ku_ids=KNOWN_KU, existing_dedup_keys=set()
    )
    assert result["passed"] is False
    assert "pii_import_disabled" in _codes(result)
    result = verify_import_batch(
        batch,
        known_ku_ids=KNOWN_KU,
        existing_dedup_keys=set(),
        authorized_pii=True,
        pii_reviewed_by="privacy reviewer",
    )
    assert result["passed"] is True


def test_g4_bad_difficulty_and_missing_field_fail():
    row = _question_row(difficulty=9, answer="")
    batch = {"import_type": "question", "rows": [row]}
    result = verify_import_batch(
        batch, known_ku_ids=KNOWN_KU, existing_dedup_keys=set()
    )
    codes = {e["code"] for row in result["row_errors"] for e in row["errors"]}
    assert "bad_difficulty" in codes
    assert "missing_field" in codes
