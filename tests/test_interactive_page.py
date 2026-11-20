"""Tests for services/interactive_page.py (aetherviz G1+G2+G3, pure functions).

No DB, no network, no LLM. The source-ledger gate (g10) is exercised
with a stub ledger_check standing in for verify_lesson_source_ledger
from the unmerged feat/narration-source-ledger-g1 branch: the stub
approves exactly when the spec carries a non-empty source_ledger with
rows, which is the wiring the router will do after that branch merges.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from services.interactive_page import (
    ALLOWED_SPEEDS,
    control_checklist,
    detect_render_mode,
    detect_subject,
    example_spec,
    transition,
    validate_controls,
    verify_interactive_page,
)

KU = "ku-newton-2nd-law"
KU_PHOTO = "ku-photosynthesis"
KNOWN_KU = {KU, KU_PHOTO, "ku-pythagorean", "ku-sine-function"}
KNOWN_TB = {"tb-renjiao-g10-math-bx2"}
ATLAS_MODELS = {"projectile_motion", "pendulum_small_angle"}


def _stub_ledger(spec):
    ledger = spec.get("source_ledger")
    rows = ledger.get("rows") if isinstance(ledger, dict) else None
    if isinstance(rows, list) and rows:
        return SimpleNamespace(passed=True, issues=[])
    return SimpleNamespace(
        passed=False,
        issues=[SimpleNamespace(field="rows", code="empty_ledger", message="ledger rows must be a non-empty list")],
    )


def _stub_ledger_dict(spec):
    result = _stub_ledger(spec)
    return {"passed": result.passed, "issues": [i.__dict__ for i in result.issues]}


def _good_spec(**overrides):
    spec = example_spec(KU)
    spec.update(overrides)
    return copy.deepcopy(spec)


def _verify(spec, **kwargs):
    kwargs.setdefault("known_ku_ids", KNOWN_KU)
    kwargs.setdefault("known_textbook_ids", KNOWN_TB)
    kwargs.setdefault("ledger_check", _stub_ledger)
    kwargs.setdefault("atlas_model_names", ATLAS_MODELS)
    return verify_interactive_page(spec, **kwargs)


def _codes(check):
    return {i.code for i in check.issues}


# ── G2：渲染模式识别 ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "topic,expected",
    [
        # README 25 主题逐条验收（按关键词规则，不是按示例表分组）。
        ("牛顿第二定律", "hybrid"),
        ("匀速运动", "three"),
        ("匀变速运动", "three"),
        ("电磁感应", "hybrid"),
        ("相对论时间膨胀", "three"),
        ("量子隧穿效应", "three"),
        ("光合作用", "three"),
        ("酸碱中和", "three"),
        ("氧化还原反应", "three"),
        ("分子结构", "three"),
        ("DNA复制", "three"),
        ("细胞呼吸", "three"),
        ("有丝分裂", "three"),
        ("遗传规律", "three"),
        # “勾股定理”“概率分布”在上游示例表里属 SVG，但关键词规则得 three：
        # 规则与示例表在此处分歧，门禁以规则为准，规格可用书面原因覆盖。
        ("勾股定理", "three"),
        ("三角函数", "svg"),
        ("正弦函数图像", "svg"),
        ("概率分布", "three"),
        ("行星运动定律", "hybrid"),
        ("宇宙膨胀", "three"),
        ("黑洞", "three"),
        ("日食月食", "three"),
        ("算法复杂度", "three"),
        ("数据结构", "three"),
        ("排序算法", "three"),
        ("设计模式", "three"),
    ],
)
def test_detect_render_mode_readme_25_topics(topic, expected):
    assert detect_render_mode(topic) == expected


def test_detect_render_mode_hybrid_priority():
    # hybrid 词优先；three+svg 同时命中也进 hybrid。
    assert detect_render_mode("牛顿运动定律与函数图像") == "hybrid"
    assert detect_render_mode("波动与函数曲线") == "hybrid"
    assert detect_render_mode("运动与函数图像") == "hybrid"
    assert detect_render_mode("函数图像") == "svg"


def test_detect_render_mode_boundaries():
    assert detect_render_mode("Photosynthesis") == "three"
    assert detect_render_mode("牛顿第二定律 Newton's Second Law") == "hybrid"
    assert detect_render_mode("函数图像 function graph") == "svg"
    with pytest.raises(ValueError):
        detect_render_mode("")
    with pytest.raises(ValueError):
        detect_render_mode("   ")


def test_detect_subject_readme_25_topics():
    expected = {
        "牛顿第二定律": "physics",
        "匀速运动": "physics",
        "匀变速运动": "physics",
        "电磁感应": "physics",
        "相对论时间膨胀": "physics",
        "量子隧穿效应": "physics",
        "光合作用": "biology",  # 上游 README 误列化学，已纠正
        "酸碱中和": "chemistry",
        "氧化还原反应": "chemistry",
        "分子结构": "chemistry",
        "DNA复制": "biology",
        "细胞呼吸": "biology",
        "有丝分裂": "biology",
        "遗传规律": "biology",
        "勾股定理": "math",
        "三角函数": "math",
        "正弦函数图像": "math",
        "概率分布": "math",
        "行星运动定律": "astronomy",
        "宇宙膨胀": "astronomy",
        "黑洞": "astronomy",
        "日食月食": "astronomy",
        "算法复杂度": "programming",
        "数据结构": "programming",
        "排序算法": "programming",
        "设计模式": "programming",
    }
    for topic, subject in expected.items():
        assert detect_subject(topic) == subject, topic
    assert detect_subject("Photosynthesis") is None
    assert detect_subject("") is None


# ── G3：交互控件契约 ─────────────────────────────────────────────────────


def _controls(**overrides):
    controls = example_spec(KU)["controls"]
    return copy.deepcopy(controls)


def test_controls_valid_and_checklist():
    controls = _controls()
    assert validate_controls(controls) == []
    rows = {r["control"]: r for r in control_checklist(controls)}
    assert rows["slider"]["status"] == "pass"
    assert rows["random_experiment"]["status"] == "pass"
    assert rows["random_experiment"]["required"] is False
    assert rows["random_experiment"]["enabled"] is False


@pytest.mark.parametrize("missing", ["slider", "play", "pause", "step", "speed", "reset", "objectives_checklist", "click_highlight"])
def test_controls_missing_required(missing):
    controls = [c for c in _controls() if c["kind"] != missing]
    assert "missing_control" in {i.code for i in validate_controls(controls)}


def test_controls_missing_random_is_fine():
    controls = [c for c in _controls() if c["kind"] != "random_experiment"]
    assert validate_controls(controls) == []


def test_controls_disabled_required_fails():
    controls = _controls()
    controls[1]["enabled"] = False  # play
    assert "control_disabled" in {i.code for i in validate_controls(controls)}


def test_controls_unknown_and_duplicate():
    controls = _controls()
    controls.append({"kind": "teleport", "enabled": True})
    assert "bad_control_kind" in {i.code for i in validate_controls(controls)}
    controls = _controls()
    controls.append({"kind": "play", "enabled": True})
    assert "duplicate_control" in {i.code for i in validate_controls(controls)}


def test_controls_slider_bounds():
    controls = _controls()
    slider = next(c for c in controls if c["kind"] == "slider")
    slider["min"] = 10
    slider["max"] = 0
    assert "bad_slider_bounds" in {i.code for i in validate_controls(controls)}
    controls = _controls()
    slider = next(c for c in controls if c["kind"] == "slider")
    slider["value"] = 99
    assert "bad_slider_value" in {i.code for i in validate_controls(controls)}
    controls = _controls()
    slider = next(c for c in controls if c["kind"] == "slider")
    slider["step"] = 0
    assert "bad_slider_step" in {i.code for i in validate_controls(controls)}


def test_controls_speed_options():
    controls = _controls()
    speed = next(c for c in controls if c["kind"] == "speed")
    speed["options"] = [0.5, 7.0]
    assert "bad_speed_options" in {i.code for i in validate_controls(controls)}
    controls = _controls()
    speed = next(c for c in controls if c["kind"] == "speed")
    speed["value"] = 4.0
    assert "bad_speed_value" in {i.code for i in validate_controls(controls)}
    assert all(s in ALLOWED_SPEEDS for s in (0.25, 0.5, 1.0, 2.0, 4.0))


def test_controls_random_requires_seed():
    controls = _controls()
    rnd = next(c for c in controls if c["kind"] == "random_experiment")
    rnd["enabled"] = True
    assert "random_requires_seed" in {i.code for i in validate_controls(controls)}
    rnd["seed"] = 42
    assert validate_controls(controls) == []
    rows = {r["control"]: r for r in control_checklist(controls)}
    assert rows["random_experiment"]["status"] == "pass"


def test_controls_objectives_count():
    controls = _controls()
    obj = next(c for c in controls if c["kind"] == "objectives_checklist")
    obj["items"] = ["只有两条", "第二条"]
    assert "bad_objectives" in {i.code for i in validate_controls(controls)}
    obj["items"] = ["一", "二", "三", "四", "五"]
    assert "bad_objectives" in {i.code for i in validate_controls(controls)}
    obj["items"] = ["一", "二", "三", "四"]
    assert validate_controls(controls) == []


def test_control_state_machine():
    assert transition("idle", "play") == "playing"
    assert transition("playing", "pause") == "paused"
    assert transition("paused", "step") == "paused"
    assert transition("paused", "play") == "playing"
    assert transition("playing", "reset") == "idle"
    assert transition("playing", "speed") == "playing"
    for state, action in [("idle", "step"), ("idle", "pause"), ("playing", "play"), ("playing", "step"), ("paused", "pause")]:
        with pytest.raises(ValueError):
            transition(state, action)
    with pytest.raises(ValueError):
        transition("nope", "play")


# ── G1：页级校验门 ───────────────────────────────────────────────────────


def test_example_spec_passes_with_stub_ledger():
    check = _verify(_good_spec())
    assert check.passed, [i.to_dict() for i in check.issues]
    assert all(check.gates[f"g{i}"] for i in range(1, 11))


def test_example_spec_passes_with_dict_ledger_result():
    check = _verify(_good_spec(), ledger_check=_stub_ledger_dict)
    assert check.passed


def test_gate_not_an_object():
    check = _verify("not-a-spec")
    assert not check.passed
    assert "not_an_object" in _codes(check)


def test_gate_bad_id_and_verified_field():
    spec = _good_spec(id="Bad ID!")
    assert "bad_id" in _codes(_verify(spec))
    spec = _good_spec()
    spec["verified"] = True
    assert "verified_field_forbidden" in _codes(_verify(spec))


def test_gate_ku_anchor_fail_closed():
    spec = _good_spec(ku_id="ku-does-not-exist")
    assert "unknown_ku" in _codes(_verify(spec))
    check = verify_interactive_page(_good_spec(), known_ku_ids=None, ledger_check=_stub_ledger, atlas_model_names=ATLAS_MODELS)
    assert "ku_existence_unchecked" in _codes(check)
    spec = _good_spec()
    del spec["ku_id"]
    assert "bad_ku_id" in _codes(_verify(spec))


def test_gate_language_must_match_topic():
    spec = _good_spec(language="en")
    assert "bad_language" in _codes(_verify(spec))


def test_gate_layout_drift_rejected():
    spec = _good_spec()
    spec["layout"]["sidebar_ratio"] = 0.25
    spec["layout"]["canvas_ratio"] = 0.75
    check = _verify(spec)
    assert not check.passed and not check.gates["g2"]
    assert {"bad_sidebar_ratio", "bad_canvas_ratio"} <= _codes(check)
    spec = _good_spec()
    spec["layout"]["quiz_panel"]["width_px"] = 400
    assert "bad_quiz_width" in _codes(_verify(spec))
    spec = _good_spec()
    spec["layout"]["quiz_panel"]["collapsible"] = False
    assert "quiz_not_collapsible" in _codes(_verify(spec))


def test_gate_subject_palette_mismatch():
    spec = _good_spec(palette_family="green")
    assert "bad_palette" in _codes(_verify(spec))
    spec = _good_spec(subject="biology", palette_family="green", topic="光合作用", render_mode="three")
    spec["title"] = {"zh": "光合作用", "en": "Photosynthesis"}
    del spec["atlas_model_ref"]
    check = _verify(spec)
    assert check.passed, [i.to_dict() for i in check.issues]


def test_gate_render_mode_override_needs_reason():
    # 勾股定理按规则得 three；声明 svg 无书面原因不过，有原因过。
    spec = _good_spec(topic="勾股定理", subject="math", palette_family="gold", render_mode="svg")
    spec["title"] = {"zh": "勾股定理", "en": "Pythagorean Theorem"}
    spec["ku_id"] = "ku-pythagorean"
    spec["assertions"] = [{"text": "直角三角形斜边的平方等于两直角边的平方和", "refs": [{"kind": "ku", "id": "ku-pythagorean"}]}]
    spec["provenance"] = {"label": "material", "sources": [{"kind": "ku", "id": "ku-pythagorean"}]}
    del spec["atlas_model_ref"]
    del spec["scene"]
    spec["svg_layer"] = {"overlay": True}
    assert "render_mode_mismatch" in _codes(_verify(spec))
    spec["render_mode_override_reason"] = "几何证明题，SVG 优先作图"
    check = _verify(spec)
    assert check.passed, [i.to_dict() for i in check.issues]


def test_gate_physics_requires_atlas_model():
    spec = _good_spec()
    del spec["atlas_model_ref"]
    assert "unknown_atlas_model" in _codes(_verify(spec))
    spec = _good_spec(atlas_model_ref="newton_model_not_registered")
    assert "unknown_atlas_model" in _codes(_verify(spec))
    # 未传注册表名集时，默认取 Atlas 注册表（主仓有 projectile_motion）。
    check = verify_interactive_page(
        _good_spec(), known_ku_ids=KNOWN_KU, ledger_check=_stub_ledger, atlas_model_names=None
    )
    assert check.passed, [i.to_dict() for i in check.issues]


def test_gate_scene_baseline():
    spec = _good_spec()
    spec["scene"]["camera"]["fov"] = 75
    assert "bad_camera" in _codes(_verify(spec))
    spec = _good_spec()
    spec["scene"]["lights"] = [{"type": "hemisphere"}]
    assert "missing_lights" in _codes(_verify(spec))
    spec = _good_spec()
    spec["scene"]["renderer"]["shadow_map"] = False
    assert "bad_renderer" in _codes(_verify(spec))


def test_gate_non_physics_vector_colors():
    spec = _good_spec(subject="chemistry", palette_family="orange-red", topic="分子结构", render_mode="three")
    spec["title"] = {"zh": "分子结构", "en": "Molecular Structure"}
    del spec["atlas_model_ref"]
    del spec["svg_layer"]
    spec["scene"]["vectors"] = [{"quantity": "force", "color": "#3B82F6"}]
    assert "bad_vector_color" in _codes(_verify(spec))
    spec["scene"]["vectors"] = [{"quantity": "force", "color": "#EF4444"}]
    check = _verify(spec)
    assert check.passed, [i.to_dict() for i in check.issues]


def test_gate_figures_go_through_teaching_figure_gate():
    spec = _good_spec()
    spec["figures"] = [{"id": "not-a-figure"}]
    check = _verify(spec)
    assert not check.passed and not check.gates["g5"]
    assert any(i.field.startswith("figures[0].") for i in check.issues)


def test_gate_dependencies_self_hosted():
    # 自托管是首选；Tailwind 在自托管 profile 里禁入（viz_generator 口径：内联样式）。
    spec = _good_spec()
    spec["dependencies"]["libraries"].append(
        {"library": "tailwind", "version": "3.4.17", "url": "/v1/edu-assets/tailwind.css"}
    )
    assert "tailwind_forbidden" in _codes(_verify(spec))
    # KaTeX 0.16.11 是上游钉死值，但仓内自托管是 0.16.8：版本漂移须显式走 cdn profile。
    spec = _good_spec()
    spec["dependencies"]["libraries"][1]["version"] = "0.16.11"
    assert "bad_library_pin" in _codes(_verify(spec))


def test_gate_dependencies_cdn_pinned():
    cdn_libs = [
        {"library": "three", "version": "r134", "url": "https://cdnjs.cloudflare.com/ajax/libs/three.js/r134/three.min.js", "integrity": "sha384-aaa"},
        {"library": "tailwind", "version": "v3.4+", "url": "https://cdn.tailwindcss.com", "integrity": "sha384-bbb"},
        {"library": "katex", "version": "0.16.11", "url": "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js", "integrity": "sha384-ccc"},
        {"library": "d3", "version": "v7", "url": "https://d3js.org/d3.v7.min.js", "integrity": "sha384-ddd"},
    ]
    spec = _good_spec()
    spec["dependencies"] = {"profile": "cdn_pinned", "requires_network": True, "offline_available": False, "libraries": cdn_libs}
    check = _verify(spec)
    assert check.passed, [i.to_dict() for i in check.issues]
    # 缺 SRI 不过（上游本身不带 SRI，此为已记录的缺口）。
    spec = _good_spec()
    libs = copy.deepcopy(cdn_libs)
    del libs[0]["integrity"]
    spec["dependencies"] = {"profile": "cdn_pinned", "requires_network": True, "offline_available": False, "libraries": libs}
    assert "missing_sri" in _codes(_verify(spec))
    # CDN 页谎称离线可用不过；版本钉死错不过。
    spec = _good_spec()
    spec["dependencies"] = {"profile": "cdn_pinned", "requires_network": True, "offline_available": True, "libraries": cdn_libs}
    assert "offline_claim" in _codes(_verify(spec))
    spec = _good_spec()
    libs = copy.deepcopy(cdn_libs)
    libs[0]["version"] = "r160"
    spec["dependencies"] = {"profile": "cdn_pinned", "requires_network": True, "offline_available": False, "libraries": libs}
    assert "bad_library_pin" in _codes(_verify(spec))
    # 未知库不过。
    spec = _good_spec()
    libs = copy.deepcopy(cdn_libs)
    libs.append({"library": "gsap", "version": "3.14.2", "url": "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js", "integrity": "sha384-eee"})
    spec["dependencies"] = {"profile": "cdn_pinned", "requires_network": True, "offline_available": False, "libraries": libs}
    assert "unknown_library" in _codes(_verify(spec))


def test_gate_output_contract():
    spec = _good_spec()
    spec["output"]["extra_files"] = ["extra.css"]
    assert "extra_files" in _codes(_verify(spec))
    spec = _good_spec()
    spec["output"]["wraps_markdown"] = True
    assert "wraps_markdown" in _codes(_verify(spec))


def test_gate_controls_fail_g8():
    spec = _good_spec()
    spec["controls"] = [c for c in spec["controls"] if c["kind"] != "play"]
    check = _verify(spec)
    assert not check.passed and not check.gates["g8"]


def test_gate_assertions_need_citations():
    spec = _good_spec(assertions=[])
    assert "missing_assertions" in _codes(_verify(spec))
    spec = _good_spec()
    spec["assertions"] = [{"text": "无出处断言", "refs": [{"kind": "ku", "id": "ku-does-not-exist"}]}]
    assert "unknown_ku" in _codes(_verify(spec))
    spec = _good_spec()
    spec["provenance"] = {"label": "material", "sources": []}
    assert "material_needs_source" in _codes(_verify(spec))


def test_gate_ledger_fail_closed():
    # 无台账字段不过；有台账但未注入门禁也不过（不把“没接门禁”当通过）。
    spec = _good_spec()
    del spec["source_ledger"]
    assert "missing_ledger" in _codes(_verify(spec))
    check = verify_interactive_page(
        _good_spec(), known_ku_ids=KNOWN_KU, ledger_check=None, atlas_model_names=ATLAS_MODELS
    )
    assert "ledger_gate_unavailable" in _codes(check)
    assert not check.passed and not check.gates["g10"]
    # 注入的门禁判不过时，g10 如实不过。
    check = verify_interactive_page(
        _good_spec(), known_ku_ids=KNOWN_KU, ledger_check=lambda s: SimpleNamespace(passed=False, issues=[]), atlas_model_names=ATLAS_MODELS
    )
    assert "ledger_failed" in _codes(check)
    # 注入的门禁抛错也不放行。
    def _boom(spec):
        raise RuntimeError("boom")

    check = verify_interactive_page(
        _good_spec(), known_ku_ids=KNOWN_KU, ledger_check=_boom, atlas_model_names=ATLAS_MODELS
    )
    assert "ledger_check_error" in _codes(check)
