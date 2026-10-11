"""圆锥曲线过定点弦 3O 链路：oprim 精确计算 / oskill 解题 / omodul 复核。

期望值取自 edulab analytic_kernel 自检（旗舰 [-3, 7/4]、焦点弦 [3, 4]、△OAB (0, 3/2]、
抛物线 OA·OB = −3）与手算（见各用例注释）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sympy as sp

from omodul.conic_chord_lesson import (
    ConicChordLessonConfig,
    ConicChordLessonInput,
    conic_chord_lesson,
)
from oprim.conic_analysis import (
    AnalyticGeometrySpec,
    ChordVieta,
    ConicSpec,
    build_conic,
    chord_vieta,
    horizontal_line_meets_twice,
    m,
    numeric_range_check,
    parse_exact_number,
    range_over_m,
)
from oskill.conic_chord_skill import solve_conic_chord

ELLIPSE = {"kind": "ellipse", "a": 2, "b": "sqrt(3)"}  # x²/4 + y²/3 = 1，F(±1, 0)
HYPERBOLA = {"kind": "hyperbola", "a": 1, "b": "sqrt(3)"}  # x² − y²/3 = 1，F(±2, 0)
PARABOLA = {"kind": "parabola", "p": 2}  # y² = 4x，F(1, 0)

FLAGSHIP = {"conic": ELLIPSE, "query": {"through": [1, 0], "target": "dot_product", "vertex": [-1, 0]}}

# (spec, [(lo, hi, lo_closed, hi_closed), ...]) ；None = ∞
RANGE_CASES = [
    # 旗舰：竖直线取 7/4，水平线（x 轴，A(2,0) B(−2,0)）取 −3
    (FLAGSHIP, [(-3, sp.Rational(7, 4), True, True)]),
    # 焦点弦：通径 2b²/a = 3 最短（竖直），长轴 2a = 4 最长（水平）
    ({"conic": ELLIPSE, "query": {"through": [1, 0], "target": "chord_length"}}, [(3, 4, True, True)]),
    # △OAB：S = 6√(1+m²)/(3m²+4)，m=0 取 3/2；水平线过 O 退化 → 0 取不到
    ({"conic": ELLIPSE, "query": {"through": [1, 0], "target": "triangle_area", "vertex": [0, 0]}},
     [(0, sp.Rational(3, 2), False, True)]),
    # △F₁AB：d = 2/√(1+m²)，S = 12√(1+m²)/(3m²+4) ∈ (0, 3]
    ({"conic": ELLIPSE, "query": {"through": [1, 0], "target": "triangle_area", "vertex": [-1, 0]}},
     [(0, 3, False, True)]),
    # 外点 P(4,0)：(3m²+4)y²+24my+36=0，Δ=144(m²−4)>0 ⇔ |m|>2；|AB|² 关于 u=m² 递增，
    # u→4⁺ 切线极限 0（开），u→∞ 水平线 y=0 弦长 4（闭）
    ({"conic": ELLIPSE, "query": {"through": [4, 0], "target": "chord_length"}}, [(0, 4, False, True)]),
    # 抛物线焦点弦：|AB| = 2p(1+m²) = 4(1+m²) ∈ [4, +∞)；水平线只交一点，m→∞ 不取到
    ({"conic": PARABOLA, "query": {"through": [1, 0], "target": "chord_length"}}, [(4, None, True, False)]),
    # 抛物线 MA·MB，M(1,0)：x1x2=1, x1+x2=4m²+2, y1y2=−4 ⇒ −4m²−4 ∈ (−∞, −4]
    ({"conic": PARABOLA, "query": {"through": [1, 0], "target": "dot_product", "vertex": [1, 0]}},
     [(None, -4, False, True)]),
    # 双曲线焦点弦：(3m²−1)y²+12my+9=0，Δ=36(m²+1)，|AB| = 6(1+m²)/|3m²−1|：
    # 同支 u∈[0,1/3) 得 [6,∞)，两支 u>1/3 得 (2,∞) 且水平线（实轴，长 2a=2）取到 ⇒ [2, +∞)
    ({"conic": HYPERBOLA, "query": {"through": [2, 0], "target": "chord_length"}}, [(2, None, True, False)]),
    # 双曲线 OA·OB = −1 + 4/(3m²−1)：同支 (−∞, −5]（竖直线 x=2 取 −5），两支 (−1, ∞) 且水平线取 −1
    ({"conic": HYPERBOLA, "query": {"through": [2, 0], "target": "dot_product", "vertex": [0, 0]}},
     [(None, -5, False, True), (-1, None, True, False)]),
]

# 非手算、仅由独立浮点复核把关的一般位置用例（驻点为无理数、过定点不在轴上 / 在中心）
GENERAL_CASES = [
    {"conic": ELLIPSE, "query": {"through": [1, 1], "target": "dot_product", "vertex": [0, "1/2"]}},
    {"conic": HYPERBOLA, "query": {"through": [0, 0], "target": "chord_length"}},
    {"conic": {"kind": "hyperbola", "a": 2, "b": 1}, "query": {"through": [3, 1], "target": "triangle_area", "vertex": [0, 0]}},
    {"conic": {"kind": "parabola", "p": "3/2"}, "query": {"through": [1, 2], "target": "dot_product", "vertex": [0, 0]}},
    {"conic": {"kind": "ellipse", "a": "2sqrt(2)", "b": 2}, "query": {"through": [-1, "1/2"], "target": "triangle_area", "vertex": [2, 0]}},
]

CONSTANT_CASES = [
    # 抛物线焦点弦 OA·OB = x1x2 + y1y2 = 1 − 4 = −3
    ({"conic": PARABOLA, "query": {"through": [1, 0], "target": "fixed_value_dot", "vertex": [0, 0]}}, sp.Integer(-3)),
    # 双曲线 M(−1,0)：MA·MB = (−3m²+5+4·(−1))/(3m²−1) + 1 = 0（竖直线 (2,±3)：9−9=0）
    ({"conic": HYPERBOLA, "query": {"through": [2, 0], "target": "fixed_value_dot", "vertex": [-1, 0]}}, sp.Integer(0)),
]


def _expect_pieces(sol, expected) -> None:
    assert len(sol.answer_pieces) == len(expected)
    for got, (lo, hi, lc, hc) in zip(sol.answer_pieces, expected):
        if lo is None:
            assert got.lo is None
        else:
            assert got.lo == pytest.approx(float(lo), abs=1e-12)
        if hi is None:
            assert got.hi is None
        else:
            assert got.hi == pytest.approx(float(hi), abs=1e-12)
        assert (got.lo_closed, got.hi_closed) == (lc, hc)


@pytest.mark.parametrize(("raw", "expected"), RANGE_CASES)
def test_skill_exact_ranges(raw: dict, expected: list) -> None:
    sol = solve_conic_chord(AnalyticGeometrySpec(**raw))
    assert sol.answer_kind == "range"
    _expect_pieces(sol, expected)
    data = sol.board_data
    assert set(data) == {"lesson", "steps", "board"}
    assert data["board"]["rangeBar"]["of"] == "target"
    assert any(r["id"] == "target" and r.get("highlight") for r in data["board"]["readouts"])
    assert data["steps"][0]["title"] == "设直线"
    assert data["steps"][-1]["title"] == "结论"
    assert sol.answer_latex in data["lesson"]["answer"]
    assert sol.title.startswith("已知")


def test_flagship_latex_and_steps() -> None:
    sol = solve_conic_chord(AnalyticGeometrySpec(**FLAGSHIP))
    assert sol.answer_latex == r"\left[-3,\ \frac{7}{4}\right]"
    assert sol.title == (
        "已知椭圆 C: x²/4+y²/3=1，点 M(-1,0)，过点 F(1,0)（焦点）的直线 l 与 C 交于 A、B 两点，"
        "求 MA·MB（向量数量积）的取值范围。"
    )
    titles = [s.title for s in sol.steps]
    assert titles == ["设直线", "联立方程", "韦达定理", "目标量的表达式", "求取值范围", "结论"]
    html = "".join(s.content for s in sol.steps)
    assert r"\left(3 m^{2} + 4\right)y^{2}+6 my-9=0" in html
    assert r"\Delta=144 \left(m^{2} + 1\right)" in html
    assert r"-3 + \frac{19}{3 m^{2} + 4}" in html
    assert "F1" not in sol.board_data["board"]["points"]  # 左焦点与 M 重合，不重复画
    board = sol.board_data["board"]
    assert board["rangeBar"]["min"] == -3.0 and board["rangeBar"]["max"] == 1.75
    assert board["conics"][0]["kind"] == "ellipse" and board["conics"][0]["name"] == "C"
    assert board["derived"][0] == {"type": "line_through_angle", "name": "l", "point": "F", "angle": "@param", "color": "line"}


def test_parabola_horizontal_line_is_not_a_chord() -> None:
    para = build_conic(ConicSpec(**PARABOLA))
    ell = build_conic(ConicSpec(**ELLIPSE))
    assert horizontal_line_meets_twice(para, through=(1, 0)) is False
    assert horizontal_line_meets_twice(ell, through=(1, 0)) is True
    assert horizontal_line_meets_twice(ell, through=(0, 2)) is False  # |y0| > b
    # 同一个有限极限：水平线不合法时端点开，合法时闭
    chord = chord_vieta(para, through=(1, 0))
    r_open = range_over_m(1 / (1 + m**2), chord=chord, horizontal_valid=False)
    r_closed = range_over_m(1 / (1 + m**2), chord=chord, horizontal_valid=True)
    assert r_open.latex == r"\left(0,\ 1\right]"
    assert r_closed.latex == r"\left[0,\ 1\right]"


@pytest.mark.parametrize(("raw", "value"), CONSTANT_CASES)
def test_skill_fixed_values(raw: dict, value: sp.Expr) -> None:
    sol = solve_conic_chord(AnalyticGeometrySpec(**raw))
    assert sol.answer_kind == "constant"
    assert sol.answer_latex == sp.latex(value)
    assert sol.constant_value == pytest.approx(float(value))
    assert sol.board_data["board"]["constant"] == {"of": "target", "label": f"${sp.latex(value)}$"}
    assert "rangeBar" not in sol.board_data["board"]


def test_fixed_value_rejected_when_not_constant(tmp_path: Path) -> None:
    raw = {"conic": ELLIPSE, "query": {"through": [1, 0], "target": "fixed_value_dot", "vertex": [-1, 0]}}
    result = conic_chord_lesson(ConicChordLessonConfig(), ConicChordLessonInput(spec=AnalyticGeometrySpec(**raw)), tmp_path)
    assert result["status"] == "failed"
    assert "not a fixed value" in result["error"]["message"]


@pytest.mark.parametrize(
    ("raw", "expected"), RANGE_CASES + [(r, None) for r, _ in CONSTANT_CASES] + [(r, None) for r in GENERAL_CASES]
)
def test_omodul_cross_check_and_pillars(raw: dict, expected: object, tmp_path: Path) -> None:
    result = conic_chord_lesson(ConicChordLessonConfig(), ConicChordLessonInput(spec=AnalyticGeometrySpec(**raw)), tmp_path)
    assert result["status"] == "completed", result["error"]
    assert result["cost_usd"] == 0
    assert len(result["fingerprint"]) == 24
    assert result["decision_trail"]["steps"] == 3
    trail = json.loads(next(tmp_path.glob("decision_trail_*.json")).read_text())
    assert [s["event"] for s in trail] == ["spec_received", "solved", "cross_checked"]
    assert trail[2]["ok"] is True
    lesson = json.loads(Path(result["report_path"]).read_text())
    assert lesson["lesson"]["title"] and lesson["board"]["conics"]


def test_cross_check_failure_is_reported_not_raised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import omodul.conic_chord_lesson as mod
    from oprim.conic_analysis import NumericRangeCheck

    def fake(*_a: object, **_k: object) -> NumericRangeCheck:
        return NumericRangeCheck(pieces=[(-3.0, 2.0)], n_samples=1, n_valid=1, sampled_min=-3.0, sampled_max=2.0)

    monkeypatch.setattr(mod, "numeric_range_check", fake)
    result = mod.conic_chord_lesson(ConicChordLessonConfig(), ConicChordLessonInput(spec=AnalyticGeometrySpec(**FLAGSHIP)), tmp_path)
    assert result["status"] == "failed"
    assert "cross-check mismatch" in result["error"]["message"]
    assert not list(tmp_path.glob("conic_chord_lesson_*.json"))


def test_on_step_callback_receives_each_step(tmp_path: Path) -> None:
    seen: list[str] = []
    conic_chord_lesson(
        ConicChordLessonConfig(write_lesson_json=False),
        ConicChordLessonInput(spec=AnalyticGeometrySpec(**FLAGSHIP)),
        tmp_path,
        on_step=lambda e: seen.append(e["event"]),
    )
    assert seen == ["spec_received", "solved", "cross_checked"]


def test_fingerprint_is_deterministic(tmp_path: Path) -> None:
    cfg = ConicChordLessonConfig(write_lesson_json=False)
    a = conic_chord_lesson(cfg, ConicChordLessonInput(spec=AnalyticGeometrySpec(**FLAGSHIP)), tmp_path)
    b = conic_chord_lesson(cfg, ConicChordLessonInput(spec=AnalyticGeometrySpec(**FLAGSHIP)), tmp_path)
    other = {"conic": ELLIPSE, "query": {"through": [1, 0], "target": "chord_length"}}
    c = conic_chord_lesson(cfg, ConicChordLessonInput(spec=AnalyticGeometrySpec(**other)), tmp_path)
    assert a["fingerprint"] == b["fingerprint"] != c["fingerprint"]


@pytest.mark.parametrize(
    "value",
    ["__import__('os').system('id')", "2**1000", "x", "sqrt(2)+1", "1/0", "1e3", "sqrt(-1)", "exec('1')",
     "S('1')", "99999", "1" * 40, True, float("nan"), float("inf"), None, [1]],
)
def test_parse_exact_number_rejects_untrusted(value: object) -> None:
    with pytest.raises(ValueError):
        parse_exact_number(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(2, sp.Integer(2)), (-1, sp.Integer(-1)), (1.5, sp.Rational(3, 2)), ("-3/2", sp.Rational(-3, 2)),
     ("2sqrt(3)", 2 * sp.sqrt(3)), ("√3", sp.sqrt(3)), ("3*sqrt(2)/2", 3 * sp.sqrt(2) / 2), ("-√2", -sp.sqrt(2))],
)
def test_parse_exact_number_accepts_literals(value: object, expected: sp.Expr) -> None:
    assert sp.simplify(parse_exact_number(value) - expected) == 0  # type: ignore[arg-type]


def test_parse_exact_number_positive_flag() -> None:
    with pytest.raises(ValueError):
        parse_exact_number("-2", positive=True)
    with pytest.raises(ValueError):
        parse_exact_number(0, positive=True)


@pytest.mark.parametrize(
    "raw",
    [
        # 恶意 / 非法字面量
        {"conic": {"kind": "ellipse", "a": "__import__('os').system('id')", "b": 1}, "query": {"through": [0, 0], "target": "chord_length"}},
        {"conic": ELLIPSE, "query": {"through": ["lambda: 0", 0], "target": "chord_length"}},
        {"conic": ELLIPSE, "query": {"through": [1, 0], "target": "dot_product", "vertex": ["1e9", 0]}},
        # 退化 / 不支持的曲线
        {"conic": {"kind": "ellipse", "a": 2, "b": 2}, "query": {"through": [0, 0], "target": "chord_length"}},  # 圆
        {"conic": {"kind": "ellipse", "a": 1, "b": 2}, "query": {"through": [0, 0], "target": "chord_length"}},  # 焦点在 y 轴
        {"conic": {"kind": "hyperbola", "a": 1, "b": 0}, "query": {"through": [2, 0], "target": "chord_length"}},
        {"conic": {"kind": "parabola", "p": -2}, "query": {"through": [1, 0], "target": "chord_length"}},
        {"conic": {"kind": "parabola", "a": 2}, "query": {"through": [1, 0], "target": "chord_length"}},
        {"conic": {"kind": "ellipse", "a": 2}, "query": {"through": [1, 0], "target": "chord_length"}},
        # 缺 / 多余顶点、三角形顶点与定点重合（每条直线都退化）
        {"conic": ELLIPSE, "query": {"through": [1, 0], "target": "dot_product"}},
        {"conic": ELLIPSE, "query": {"through": [1, 0], "target": "chord_length", "vertex": [0, 0]}},
        {"conic": ELLIPSE, "query": {"through": [1, 0], "target": "triangle_area", "vertex": [1, 0]}},
    ],
)
def test_invalid_specs_fail_cleanly(raw: dict, tmp_path: Path) -> None:
    result = conic_chord_lesson(ConicChordLessonConfig(), ConicChordLessonInput(spec=AnalyticGeometrySpec(**raw)), tmp_path)
    assert result["status"] == "failed"
    assert result["error"]["type"] == "ValueError"
    assert not list(tmp_path.glob("conic_chord_lesson_*.json"))


def test_range_rejects_family_without_any_chord() -> None:
    # 任何点都存在割线（这些圆锥曲线下 "无弦" 构型不会出现），故直接构造一族 Δ<0 恒成立的方程验证守卫
    chord = ChordVieta(through=(0, 0), c=sp.Integer(0), qa=sp.Integer(1), qb=sp.Integer(0), qc=1 + m**2,
                       y_sum=sp.Integer(0), y_prod=1 + m**2, x_sum=sp.Integer(0), x_prod=sp.Integer(0),
                       disc=-4 * (1 + m**2))
    with pytest.raises(ValueError, match="no line"):
        range_over_m(m**2, chord=chord, horizontal_valid=False)


def test_spec_rejects_unknown_fields_and_language() -> None:
    with pytest.raises(ValueError):
        AnalyticGeometrySpec(conic=ELLIPSE, query={"through": [1, 0], "target": "chord_length", "evil": 1})
    with pytest.raises(ValueError):
        AnalyticGeometrySpec(conic=ELLIPSE, query={"through": [1, 0], "target": "chord_length"}, language="en")
    with pytest.raises(ValueError):
        AnalyticGeometrySpec(conic=ELLIPSE, query={"through": [1, 0], "target": "slope_product"})


def test_numeric_check_is_independent_of_sympy() -> None:
    got = numeric_range_check("ellipse", a=2.0, b=3**0.5, through=(1.0, 0.0), target="dot_product", vertex=(-1.0, 0.0))
    assert len(got.pieces) == 1
    assert got.pieces[0][0] == pytest.approx(-3.0, abs=1e-9)
    assert got.pieces[0][1] == pytest.approx(1.75, abs=1e-9)
    para = numeric_range_check("parabola", p=2.0, through=(1.0, 0.0), target="fixed_value_dot", vertex=(0.0, 0.0))
    assert para.sampled_min == pytest.approx(-3.0, abs=1e-6) and para.sampled_max == pytest.approx(-3.0, abs=1e-6)


def test_board_template_placeholder_and_injection() -> None:
    template = (Path(__file__).resolve().parent.parent / "services" / "assets" / "conic_geometry" / "board.html").read_text(encoding="utf-8")
    assert template.count("__LESSON_DATA__") == 1
    assert '<script id="lesson-data" type="application/json">__LESSON_DATA__</script>' in template
    sol = solve_conic_chord(AnalyticGeometrySpec(**FLAGSHIP))
    payload = json.dumps(sol.board_data, ensure_ascii=False).replace("<", "\\u003c")
    html = template.replace("__LESSON_DATA__", payload)
    assert "__LESSON_DATA__" not in html and "</script><" not in payload
    assert json.loads(payload)["lesson"]["answer"] == sol.board_data["lesson"]["answer"]
