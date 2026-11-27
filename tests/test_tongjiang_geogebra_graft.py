"""铜匠事实表 + GeoGebra 动态图嫁接测试（纯函数，无 DB、无网络、无 LLM）。"""

from __future__ import annotations

import copy
import math

import pytest

from services.dynamic_figure import (
    ExpressionError,
    evaluate_dynamic_figure,
    evaluate_expression,
    example_dynamic_figure,
    parse_expression,
    slider_sweep,
    validate_expression,
    verify_dynamic_figure,
)
from services.fact_table import (
    example_catalog,
    example_fact_table,
    verify_fact_table,
    verify_lesson_catalog,
)

DEMO_TEXTBOOKS = {"demo-textbook"}
DEMO_KU = {"demo-ku-quadratic"}
DEMO_ATLAS = {"pendulum_small_angle", "projectile_motion"}


def _ledger_ok(_table):
    return True


def _ledger_no(_table):
    return False


def _ledger_boom(_table):
    raise RuntimeError("ledger exploded")


def _table(**overrides):
    table = example_fact_table()
    table.update(overrides)
    return table


def _verify_table(table, **kwargs):
    kwargs.setdefault("known_textbook_ids", DEMO_TEXTBOOKS)
    kwargs.setdefault("ledger_check", _ledger_ok)
    return verify_fact_table(table, **kwargs)


def _codes(result):
    return {i.code for i in result.issues}


# ── 事实表 ─────────────────────────────────────────────────────────────


def test_example_fact_table_passes_all_gates():
    result = _verify_table(example_fact_table())
    assert result.passed, [f"{i.field}:{i.code}:{i.message}" for i in result.issues]
    assert all(result.gates.values())


def test_fact_table_ledger_not_injected_fails_closed():
    result = verify_fact_table(
        example_fact_table(), known_textbook_ids=DEMO_TEXTBOOKS)
    assert not result.passed
    assert "ledger_gate_unavailable" in _codes(result)
    assert result.gates["f8"] is False


def test_fact_table_ledger_reject_fails():
    result = _verify_table(example_fact_table(), ledger_check=_ledger_no)
    assert not result.passed
    assert "ledger_failed" in _codes(result)


def test_fact_table_ledger_error_does_not_pass():
    result = _verify_table(example_fact_table(), ledger_check=_ledger_boom)
    assert not result.passed
    assert "ledger_check_error" in _codes(result)


def test_fact_table_a_fact_without_page_fails():
    table = _table()
    table["facts"][0]["source"] = {"kind": "textbook", "ref": "demo-textbook"}
    result = _verify_table(table)
    assert not result.passed
    assert "bad_page" in _codes(result)
    assert result.gates["f2"] is False


def test_fact_table_duplicate_a_id_fails():
    table = _table()
    table["facts"][1]["id"] = "A1.1"
    result = _verify_table(table)
    assert "duplicate_a_id" in _codes(result)


def test_fact_table_a_statement_mentioning_setting_fails_f6():
    table = _table()
    table["facts"][0]["statement"] = "按设定 B1 的摆角做实验。"
    result = _verify_table(table)
    assert "a_fact_mentions_setting" in _codes(result)
    assert result.gates["f6"] is False


def test_fact_table_setting_claiming_source_fact_fails():
    table = _table()
    table["settings"][0]["value"]["kind"] = "source_fact"
    result = _verify_table(table)
    assert "setting_claims_source_fact" in _codes(result)
    assert result.gates["f3"] is False


def test_fact_table_setting_unknown_a_basis_fails_only_f3():
    table = _table()
    table["settings"][0]["basis"] = ["A9.9"]
    result = _verify_table(table)
    assert "unknown_a_fact" in _codes(result)
    assert result.gates["f3"] is False
    assert result.gates["f4"] is True
    assert result.gates["f5"] is True


def test_fact_table_step_basis_using_setting_fails_only_f4():
    table = _table()
    table["steps"][0]["basis"] = ["B1"]
    result = _verify_table(table)
    assert "basis_uses_setting" in _codes(result)
    assert result.gates["f4"] is False
    assert result.gates["f3"] is True


def test_fact_table_step_without_expected_reading_fails():
    table = _table()
    del table["steps"][0]["expected_reading"]
    result = _verify_table(table)
    assert "bad_reading" in _codes(result)


def test_fact_table_question_without_answer_fails():
    table = _table()
    table["questions"][0]["answer"] = "  "
    result = _verify_table(table)
    assert "bad_answer" in _codes(result)
    assert result.gates["f5"] is False


def test_fact_table_assertions_unknown_textbook_fails():
    result = _verify_table(example_fact_table(), known_textbook_ids={"other-book"})
    assert not result.passed
    assert "unknown_textbook" in _codes(result)
    assert result.gates["f7"] is False


def test_fact_table_assertions_empty_fails():
    result = _verify_table(_table(assertions=[]))
    assert "assertions_required" in _codes(result)


def test_fact_table_bad_subject_fails():
    result = _verify_table(_table(subject="history"))
    assert "bad_subject" in _codes(result)


def test_fact_table_not_object_fails():
    result = verify_fact_table("not a table")
    assert not result.passed
    assert "not_object" in _codes(result)


# ── catalog ────────────────────────────────────────────────────────────


def test_example_catalog_passes():
    catalog = example_catalog()
    tables = {"demo-pendulum-fact-table": example_fact_table()}
    result = verify_lesson_catalog(catalog, fact_tables=tables,
                                   known_atlas_models=DEMO_ATLAS)
    assert result.passed, [f"{i.field}:{i.code}:{i.message}" for i in result.issues]
    assert all(result.gates.values())


def test_catalog_unknown_fact_table_fails():
    result = verify_lesson_catalog(example_catalog(), fact_tables={},
                                   known_atlas_models=DEMO_ATLAS)
    assert "unknown_fact_table" in _codes(result)
    assert result.gates["c2"] is False


def test_catalog_fact_tables_unchecked_fails_closed():
    result = verify_lesson_catalog(example_catalog(),
                                   known_atlas_models=DEMO_ATLAS)
    assert "fact_tables_unchecked" in _codes(result)


def test_catalog_step_not_in_fact_table_fails():
    catalog = example_catalog()
    catalog["lessons"][0]["step_ids"] = ["S9"]
    tables = {"demo-pendulum-fact-table": example_fact_table()}
    result = verify_lesson_catalog(catalog, fact_tables=tables,
                                   known_atlas_models=DEMO_ATLAS)
    assert "unknown_ref" in _codes(result)
    assert result.gates["c3"] is False


def test_catalog_projectile_without_atlas_ref_fails():
    catalog = example_catalog()
    lesson = catalog["lessons"][0]
    lesson["title"] = "平抛运动"
    lesson["topic_keywords"] = ["平抛"]
    lesson.pop("atlas_model_ref")
    tables = {"demo-pendulum-fact-table": example_fact_table()}
    result = verify_lesson_catalog(catalog, fact_tables=tables,
                                   known_atlas_models=DEMO_ATLAS)
    assert "atlas_overlap_unresolved" in _codes(result)
    assert result.gates["c5"] is False


def test_catalog_projectile_with_atlas_ref_passes():
    catalog = example_catalog()
    lesson = catalog["lessons"][0]
    lesson["title"] = "平抛运动"
    lesson["topic_keywords"] = ["平抛", "projectile"]
    lesson["atlas_model_ref"] = "projectile_motion"
    tables = {"demo-pendulum-fact-table": example_fact_table()}
    result = verify_lesson_catalog(catalog, fact_tables=tables,
                                   known_atlas_models=DEMO_ATLAS)
    assert result.passed, [f"{i.field}:{i.code}:{i.message}" for i in result.issues]


def test_catalog_atlas_ref_unchecked_fails_closed():
    catalog = example_catalog()
    tables = {"demo-pendulum-fact-table": example_fact_table()}
    result = verify_lesson_catalog(catalog, fact_tables=tables)
    assert "atlas_models_unchecked" in _codes(result)


def test_catalog_unknown_atlas_model_fails():
    catalog = example_catalog()
    catalog["lessons"][0]["atlas_model_ref"] = "no_such_model"
    tables = {"demo-pendulum-fact-table": example_fact_table()}
    result = verify_lesson_catalog(catalog, fact_tables=tables,
                                   known_atlas_models=DEMO_ATLAS)
    assert "unknown_atlas_model" in _codes(result)


def test_catalog_duplicate_lesson_id_fails():
    catalog = example_catalog()
    catalog["lessons"].append(copy.deepcopy(catalog["lessons"][0]))
    tables = {"demo-pendulum-fact-table": example_fact_table()}
    result = verify_lesson_catalog(catalog, fact_tables=tables,
                                   known_atlas_models=DEMO_ATLAS)
    assert "duplicate_lesson_id" in _codes(result)


def test_catalog_empty_chapter_fails():
    catalog = example_catalog()
    catalog["lessons"][0]["textbook_chapter"] = ""
    tables = {"demo-pendulum-fact-table": example_fact_table()}
    result = verify_lesson_catalog(catalog, fact_tables=tables,
                                   known_atlas_models=DEMO_ATLAS)
    assert "bad_chapter" in _codes(result)


# ── 动态图：表达式求值器 ───────────────────────────────────────────────


def test_expression_arithmetic_and_power():
    assert evaluate_expression("2*(3+4)^2", {}) == 98.0
    assert evaluate_expression("10/4", {}) == 2.5
    assert evaluate_expression("-3+5", {}) == 2.0


def test_expression_functions_and_constants():
    assert evaluate_expression("sin(pi/2)", {}) == pytest.approx(1.0)
    assert evaluate_expression("sqrt(16)+abs(-3)", {}) == 7.0
    assert evaluate_expression("a*x^2+b", {"a": 1, "x": 2, "b": 0}) == 4.0


def test_expression_unknown_variable_raises():
    with pytest.raises(ExpressionError):
        evaluate_expression("a+z", {"a": 1})


def test_expression_division_by_zero_raises():
    with pytest.raises(ExpressionError):
        evaluate_expression("1/(x-5)", {"x": 5})


def test_expression_rejects_code_execution():
    with pytest.raises(ExpressionError):
        evaluate_expression("__import__('os')", {})
    with pytest.raises(ExpressionError):
        evaluate_expression("os.system(1)", {})
    with pytest.raises(ExpressionError):
        evaluate_expression("eval(x)", {"x": 1})


def test_validate_expression_unknown_identifier():
    problems = validate_expression("a*z+1", {"a"})
    assert any("z" in p for p in problems)
    assert validate_expression("a*x^2+b", {"a", "x", "b"}) == []


def test_parse_expression_rejects_trailing_tokens():
    with pytest.raises(ExpressionError):
        parse_expression("1+2)")


# ── 动态图：验证门 ─────────────────────────────────────────────────────


def test_example_dynamic_figure_passes_all_gates():
    result = verify_dynamic_figure(example_dynamic_figure(),
                                   known_ku_ids=DEMO_KU)
    assert result.passed, [f"{i.field}:{i.code}:{i.message}" for i in result.issues]
    assert all(result.gates.values())
    assert any("outlink only" in n for n in result.notes)


def test_dynamic_figure_ku_unchecked_fails_closed():
    result = verify_dynamic_figure(example_dynamic_figure())
    assert "ku_existence_unchecked" in _codes(result)
    assert result.gates["d2"] is False


def test_dynamic_figure_unknown_ku_fails():
    result = verify_dynamic_figure(example_dynamic_figure(),
                                   known_ku_ids={"other-ku"})
    assert "ku_not_found" in _codes(result)


def test_dynamic_figure_default_out_of_range_fails():
    spec = example_dynamic_figure()
    spec["parameters"][0]["default"]["value"] = 9.0
    result = verify_dynamic_figure(spec, known_ku_ids=DEMO_KU)
    assert "default_out_of_range" in _codes(result)


def test_dynamic_figure_zero_step_fails():
    spec = example_dynamic_figure()
    spec["parameters"][0]["step"]["value"] = 0
    result = verify_dynamic_figure(spec, known_ku_ids=DEMO_KU)
    assert "bad_step" in _codes(result)


def test_dynamic_figure_duplicate_param_fails():
    spec = example_dynamic_figure()
    spec["parameters"].append(copy.deepcopy(spec["parameters"][0]))
    result = verify_dynamic_figure(spec, known_ku_ids=DEMO_KU)
    assert "duplicate_param_name" in _codes(result)


def test_dynamic_figure_reserved_param_name_fails():
    spec = example_dynamic_figure()
    spec["parameters"][0]["name"] = "pi"
    result = verify_dynamic_figure(spec, known_ku_ids=DEMO_KU)
    assert "reserved_param_name" in _codes(result)


def test_dynamic_figure_unknown_expression_var_fails():
    spec = example_dynamic_figure()
    spec["readouts"][0]["expression"] = "a*z^2+b"
    result = verify_dynamic_figure(spec, known_ku_ids=DEMO_KU)
    assert "bad_expression" in _codes(result)
    assert result.gates["d4"] is False


def test_dynamic_figure_expected_mismatch_fails():
    spec = example_dynamic_figure()
    spec["readouts"][0]["expected"]["value"] = 5.0
    result = verify_dynamic_figure(spec, known_ku_ids=DEMO_KU)
    assert "expectation_mismatch" in _codes(result)
    assert result.gates["d5"] is False


def test_dynamic_figure_expected_must_be_calculation():
    spec = example_dynamic_figure()
    spec["readouts"][0]["expected"]["kind"] = "illustrative"
    result = verify_dynamic_figure(spec, known_ku_ids=DEMO_KU)
    assert "expected_not_calculation" in _codes(result)


def test_dynamic_figure_division_by_zero_at_extreme_fails():
    spec = example_dynamic_figure()
    spec["readouts"][0]["expression"] = "1/(x-5)"
    spec["readouts"][0]["expected"] = {
        "value": -1 / 3, "unit": "1", "kind": "calculation",
        "note": "x=2 时 1/(2-5)=-1/3",
    }
    result = verify_dynamic_figure(spec, known_ku_ids=DEMO_KU)
    assert not result.passed
    assert "extreme_not_finite" in _codes(result)
    assert result.gates["d6"] is False


def test_dynamic_figure_bad_renderer_fails():
    spec = example_dynamic_figure()
    spec["renderer"] = "webgl"
    result = verify_dynamic_figure(spec, known_ku_ids=DEMO_KU)
    assert "bad_renderer" in _codes(result)


def test_dynamic_figure_view_leaking_param_fails():
    spec = example_dynamic_figure()
    spec["view"] = {"a": 1, "viewport": {"width": 640, "height": 480}}
    result = verify_dynamic_figure(spec, known_ku_ids=DEMO_KU)
    assert "view_state_leak" in _codes(result)
    assert result.gates["d7"] is False


def test_dynamic_figure_non_geogebra_reference_fails():
    spec = example_dynamic_figure()
    spec["geogebra_reference"] = "https://example.com/calc"
    result = verify_dynamic_figure(spec, known_ku_ids=DEMO_KU)
    assert "bad_geogebra_reference" in _codes(result)


def test_dynamic_figure_assertions_unknown_ku_fails():
    result = verify_dynamic_figure(example_dynamic_figure(),
                                   known_ku_ids={"other-ku"})
    assert "unknown_ku" in _codes(result)


def test_dynamic_figure_title_missing_language_fails():
    spec = example_dynamic_figure()
    spec["title"] = {"zh": "抛物线参数滑块", "en": ""}
    result = verify_dynamic_figure(spec, known_ku_ids=DEMO_KU)
    assert "missing_language" in _codes(result)


# ── 动态图：求值与滑块扫描 ─────────────────────────────────────────────


def test_evaluate_dynamic_figure_defaults_and_overrides():
    spec = example_dynamic_figure()
    result = evaluate_dynamic_figure(spec)
    assert result["readouts"]["y"] == 4.0
    assert result["parameters"] == {"a": 1.0, "b": 0.0, "x": 2.0}
    assert evaluate_dynamic_figure(spec, {"a": 2.0})["readouts"]["y"] == 8.0
    assert evaluate_dynamic_figure(spec, {"x": 5.0})["readouts"]["y"] == 25.0


def test_evaluate_dynamic_figure_clamps_out_of_range():
    spec = example_dynamic_figure()
    result = evaluate_dynamic_figure(spec, {"a": 99.0})
    assert result["clamped"] == ["a"]
    assert result["parameters"]["a"] == 2.0
    assert result["readouts"]["y"] == 8.0


def test_evaluate_dynamic_figure_deterministic():
    spec = example_dynamic_figure()
    assert evaluate_dynamic_figure(spec) == evaluate_dynamic_figure(spec)


def test_slider_sweep_covers_extremes():
    sweep = slider_sweep(example_dynamic_figure())
    assert sweep["a"]["min"]["y"] == pytest.approx(2.0)
    assert sweep["a"]["default"]["y"] == pytest.approx(4.0)
    assert sweep["a"]["max"]["y"] == pytest.approx(8.0)
    assert sweep["x"]["max"]["y"] == pytest.approx(25.0)


def test_slider_sweep_uses_math_module():
    assert math.isclose(slider_sweep(example_dynamic_figure())["b"]["max"]["y"], 6.0)
