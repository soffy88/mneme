"""化学方程式配平 3O 链路：oprim 解析 / 配平 / 复核，oskill 分步解析，omodul 支柱。

期望系数取自中学教材标准答案（手算核对）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import omodul.equation_balancing_lesson as lesson_mod
from omodul.equation_balancing_lesson import (
    EquationBalancingLessonConfig,
    EquationBalancingLessonInput,
    equation_balancing_lesson,
)
from oprim.chemical_equation import (
    CHARGE_ROW,
    ReactionSpec,
    atom_conservation_table,
    balance_coefficients,
    composition_matrix,
    format_equation_latex,
    formula_latex,
    molar_mass,
    numeric_balance_check,
    parse_formula,
)
from oskill.equation_balancing_skill import balance_equation

KNOWN = [
    ("Fe2O3 + CO -> Fe + CO2", [1, 3, 2, 3]),
    ("KMnO4 + HCl -> KCl + MnCl2 + Cl2 + H2O", [2, 16, 2, 2, 5, 8]),
    ("C3H8 + O2 -> CO2 + H2O", [1, 5, 3, 4]),
    ("Ca(OH)2 + HCl -> CaCl2 + H2O", [1, 2, 1, 2]),
    ("CuSO4·5H2O -> CuSO4 + H2O", [1, 1, 5]),
    ("MnO4^- + Fe^2+ + H^+ -> Mn^2+ + Fe^3+ + H2O", [1, 5, 8, 1, 5, 4]),
    ("H2O2 = H2O + O2", [2, 2, 1]),
    ("Al + H2SO4 -> Al2(SO4)3 + H2", [2, 3, 1, 3]),
    ("Cu + HNO3 -> Cu(NO3)2 + NO + H2O", [3, 8, 3, 2, 4]),
    ("Cr2O7^{2-} + Fe^2+ + H^+ -> Cr^3+ + Fe^3+ + H2O", [1, 6, 14, 2, 6, 7]),
]


def _spec(eq: str) -> ReactionSpec:
    return ReactionSpec.from_equation(eq)


# ── oprim ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("eq", "expected"), KNOWN)
def test_oprims_balance_known_equations(eq: str, expected: list[int]) -> None:
    spec = _spec(eq)
    parsed = [parse_formula(f) for f in spec.reactants + spec.products]
    matrix = composition_matrix(parsed, n_reactants=len(spec.reactants))
    coefs = balance_coefficients(matrix)
    assert coefs == expected
    assert all(r.balanced for r in atom_conservation_table(matrix, coefficients=coefs))
    check = numeric_balance_check(coefs, reactants=spec.reactants, products=spec.products)
    assert check.ok, check.problems


@pytest.mark.parametrize(
    ("formula", "counts", "charge", "normalized"),
    [
        ("Fe2O3", {"Fe": 2, "O": 3}, 0, "Fe2O3"),
        ("Ca(OH)2", {"Ca": 1, "O": 2, "H": 2}, 0, "Ca(OH)2"),
        ("CuSO4·5H2O", {"Cu": 1, "S": 1, "O": 9, "H": 10}, 0, "CuSO4·5H2O"),
        ("Na2CO3.10H2O", {"Na": 2, "C": 1, "O": 13, "H": 20}, 0, "Na2CO3·10H2O"),
        ("K3[Fe(CN)6]", {"K": 3, "Fe": 1, "C": 6, "N": 6}, 0, "K3[Fe(CN)6]"),
        ("MnO4^-", {"Mn": 1, "O": 4}, -1, "MnO4^-"),
        ("Fe^2+", {"Fe": 1}, 2, "Fe^2+"),
        ("SO4^{2-}", {"S": 1, "O": 4}, -2, "SO4^2-"),
        ("Al^+3", {"Al": 1}, 3, "Al^3+"),
        ("H₂O", {"H": 2, "O": 1}, 0, "H2O"),
        ("Co", {"Co": 1}, 0, "Co"),
        ("CO", {"C": 1, "O": 1}, 0, "CO"),
    ],
)
def test_parse_formula(formula: str, counts: dict, charge: int, normalized: str) -> None:
    p = parse_formula(formula)
    assert p.counts == counts
    assert list(p.counts) == list(counts)  # 首次出现顺序
    assert p.charge == charge
    assert p.formula == normalized


@pytest.mark.parametrize(
    "bad",
    [
        "Xx",
        "Xx2O",
        "__import__('os')",
        "__import__('os').system('id')",
        "eval(1)",
        "exec",
        "H2O; rm -rf /",
        "lambda: 0",
        "h2o",
        "2H2O",
        "H0",
        "H02",
        "H1000",
        "Ca(OH",
        "Ca)OH(2",
        "Ca(OH]2",
        "()",
        "H2O·",
        "·H2O",
        "CuSO4·50H2O",
        "Fe^2+^3+",
        "Fe^0+",
        "Fe^22+",
        "Fe2+",
        "Fe^",
        "^2+",
        "((((H))))",
        "C" + "H" * 60,
        "",
        "   ",
        "H2O ",
    ],
)
def test_parse_formula_rejects_untrusted_or_malformed(bad: str) -> None:
    if bad == "H2O ":  # 两端空白被容忍
        assert parse_formula(bad).formula == "H2O"
        return
    with pytest.raises(ValueError):
        parse_formula(bad)


def test_parse_formula_rejects_non_string() -> None:
    with pytest.raises(ValueError):
        parse_formula(123)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("formula", "mass"),
    [
        ("H2O", 18.0),
        ("CO2", 44.0),
        ("NaCl", 58.5),
        ("Fe2O3", 160.0),
        ("KMnO4", 158.0),
        ("CaCO3", 100.0),
        ("Ca(OH)2", 74.0),
        ("H2SO4", 98.0),
        ("CuSO4·5H2O", 250.0),
        ("Al2(SO4)3", 342.0),
        ("BaSO4", 233.0),
        ("AgNO3", 170.0),
        ("ZnCl2", 136.0),
        ("MgCl2", 95.0),
        ("KClO3", 122.5),
        ("SO4^2-", 96.0),
    ],
)
def test_molar_mass(formula: str, mass: float) -> None:
    assert molar_mass(parse_formula(formula)) == mass


def test_molar_mass_outside_table() -> None:
    with pytest.raises(ValueError):
        molar_mass(parse_formula("UF6"))


def test_formula_and_equation_latex() -> None:
    assert formula_latex("Fe2O3") == r"\mathrm{Fe_{2}O_{3}}"
    assert formula_latex("CuSO4·5H2O") == r"\mathrm{CuSO_{4}\cdot 5H_{2}O}"
    assert formula_latex("MnO4^-") == r"\mathrm{MnO_{4}}^{-}"
    assert formula_latex("Ca(OH)2") == r"\mathrm{Ca(OH)_{2}}"
    tex = format_equation_latex([1, 3, 2, 3], reactants=["Fe2O3", "CO"], products=["Fe", "CO2"])
    assert tex == r"\mathrm{Fe_{2}O_{3}} + 3\,\mathrm{CO} \rightarrow 2\,\mathrm{Fe} + 3\,\mathrm{CO_{2}}"
    assert r"\ce" not in tex
    with pytest.raises(ValueError):
        format_equation_latex([1, 0, 2, 3], reactants=["Fe2O3", "CO"], products=["Fe", "CO2"])


def test_composition_matrix_adds_charge_row_only_for_ions() -> None:
    neutral = composition_matrix([parse_formula("H2"), parse_formula("O2"), parse_formula("H2O")], n_reactants=2)
    assert CHARGE_ROW not in neutral.rows
    ionic = composition_matrix([parse_formula(f) for f in ("Zn", "Cu^2+", "Zn^2+", "Cu")], n_reactants=2)
    assert ionic.rows[-1] == CHARGE_ROW
    assert ionic.matrix[-1] == [0, 2, 2, 0]
    assert balance_coefficients(ionic) == [1, 1, 1, 1]


@pytest.mark.parametrize(
    ("eq", "needle"),
    [
        ("H2 + O2 -> H2O2 + H2O", "多解"),  # 两个独立反应叠加
        ("Zn + HCl -> ZnCl2", "只出现在"),  # H 只出现在反应物一侧
        ("Na + Cl2 -> NaCl + O2", "只出现在"),  # O 只出现在生成物一侧
        ("Na + H2O -> NaOH", "无法配平"),  # 只有零解
        ("Fe^2+ -> Fe^3+", "无法配平"),  # 电荷不守恒（缺电子）
        ("H2O -> H2 + O2 + H2O2", "多解"),
    ],
)
def test_unbalanceable_or_ambiguous_rejected(eq: str, needle: str) -> None:
    spec = _spec(eq)
    parsed = [parse_formula(f) for f in spec.reactants + spec.products]
    with pytest.raises(ValueError, match=needle):
        balance_coefficients(composition_matrix(parsed, n_reactants=len(spec.reactants)))


def test_non_positive_solution_rejected() -> None:
    # 方向写反的"反应"：唯一解里出现负系数
    spec = ReactionSpec(reactants=["CO2", "O2"], products=["CO"])
    parsed = [parse_formula(f) for f in spec.reactants + spec.products]
    with pytest.raises(ValueError, match="非正"):
        balance_coefficients(composition_matrix(parsed, n_reactants=2))


def test_numeric_check_is_independent_and_catches_errors() -> None:
    r, p = ["Fe2O3", "CO"], ["Fe", "CO2"]
    assert numeric_balance_check([1, 3, 2, 3], reactants=r, products=p).ok
    bad = numeric_balance_check([1, 2, 2, 3], reactants=r, products=p)
    assert not bad.ok and any(s.startswith("O:") for s in bad.problems)
    assert not numeric_balance_check([2, 6, 4, 6], reactants=r, products=p).ok  # 非最简
    assert not numeric_balance_check([1, 3, 2], reactants=r, products=p).ok
    assert not numeric_balance_check([1, -3, 2, 3], reactants=r, products=p).ok
    ionic = numeric_balance_check(
        [1, 5, 8, 1, 5, 4], reactants=["MnO4^-", "Fe^2+", "H^+"], products=["Mn^2+", "Fe^3+", "H2O"]
    )
    assert ionic.ok and ionic.totals[CHARGE_ROW] == [17, 17]
    wrong_charge = numeric_balance_check([1, 1], reactants=["Fe^2+"], products=["Fe^3+"])
    assert not wrong_charge.ok


# ── spec ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        {"reactants": ["__import__('os')"], "products": ["H2O"]},
        {"reactants": ["H2 O2"], "products": ["H2O"]},
        {"reactants": ["H" * 41], "products": ["H2"]},
        {"reactants": [], "products": ["H2O"]},
        {"reactants": ["H2"] * 1 + ["O2", "N2", "Cl2", "F2", "Br2", "I2"], "products": ["H2O"]},
        {"reactants": ["H2O"], "products": ["H2O"]},
        {"reactants": ["H2"], "products": ["H2O"], "language": "en"},
        {"reactants": ["H2"], "products": ["H2O"], "extra": 1},
    ],
)
def test_spec_rejects_bad_input(raw: dict) -> None:
    with pytest.raises(ValidationError):
        ReactionSpec(**raw)


def test_from_equation_splits_ionic_plus_signs() -> None:
    spec = ReactionSpec.from_equation("H^+ + OH^- → H2O")
    assert spec.reactants == ["H^+", "OH^-"]
    assert spec.products == ["H2O"]
    with pytest.raises(ValueError):
        ReactionSpec.from_equation("H2 + O2")
    with pytest.raises(ValueError):
        ReactionSpec.from_equation("A -> B -> C")


# ── oskill ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("eq", "expected"), KNOWN)
def test_skill_solution(eq: str, expected: list[int]) -> None:
    sol = balance_equation(_spec(eq))
    assert sol.coefficients == expected
    titles = ["写出各物质组成", "列原子守恒方程组", "求解最小正整数解", "检验守恒", "结论"]
    assert [s.title for s in sol.steps] == titles
    assert all(r.balanced for r in sol.conservation)
    assert sol.equation_latex in sol.steps[-1].content
    assert sol.lesson_data["lesson"]["coefficients"] == expected
    json.dumps(sol.model_dump(), ensure_ascii=False)


def test_skill_plain_text_and_masses() -> None:
    sol = balance_equation(_spec("KMnO4 + HCl -> KCl + MnCl2 + Cl2 + H2O"))
    assert sol.equation_text == "2KMnO₄ + 16HCl → 2KCl + 2MnCl₂ + 5Cl₂ + 8H₂O"
    assert sol.molar_masses == {"KMnO4": 158.0, "HCl": 36.5, "KCl": 74.5, "MnCl2": 126.0, "Cl2": 71.0, "H2O": 18.0}

    hyd = balance_equation(_spec("CuSO4·5H2O -> CuSO4 + H2O"))
    assert hyd.equation_text == "CuSO₄·5H₂O → CuSO₄ + 5H₂O"
    assert hyd.molar_masses["CuSO4·5H2O"] == 250.0

    ion = balance_equation(_spec("MnO4^- + Fe^2+ + H^+ -> Mn^2+ + Fe^3+ + H2O"))
    assert ion.equation_text == "MnO₄⁻ + 5Fe²⁺ + 8H⁺ → Mn²⁺ + 5Fe³⁺ + 4H₂O"
    assert ion.conservation[-1].row == CHARGE_ROW
    assert (ion.conservation[-1].left, ion.conservation[-1].right) == (17, 17)
    assert "电荷" in ion.steps[1].content


def test_skill_mass_none_outside_table() -> None:
    sol = balance_equation(_spec("U + F2 -> UF6"))
    assert sol.coefficients == [1, 3, 1]
    assert sol.molar_masses["UF6"] is None
    assert sol.molar_masses["F2"] == 38.0


def test_skill_raises_on_unknown_element() -> None:
    with pytest.raises(ValueError, match="unknown element"):
        balance_equation(ReactionSpec(reactants=["Xx", "O2"], products=["XxO2"]))


# ── omodul ───────────────────────────────────────────────────────────────────


def _run(eq: str, tmp_path: Path, **kw: object) -> dict:
    return equation_balancing_lesson(
        EquationBalancingLessonConfig(**kw), EquationBalancingLessonInput(spec=_spec(eq)), tmp_path
    )


@pytest.mark.parametrize(("eq", "expected"), KNOWN)
def test_omodul_pillars(eq: str, expected: list[int], tmp_path: Path) -> None:
    result = _run(eq, tmp_path)
    assert result["status"] == "completed", result["error"]
    assert result["solution"]["coefficients"] == expected
    assert result["cost_usd"] == 0
    assert len(result["fingerprint"]) == 24
    assert result["decision_trail"]["steps"] == 3
    trail = json.loads(next(tmp_path.glob("decision_trail_*.json")).read_text())
    assert [s["event"] for s in trail] == ["spec_received", "balanced", "cross_checked"]
    assert trail[-1]["ok"] is True
    lesson = json.loads(Path(result["report_path"]).read_text())
    assert lesson["lesson"]["coefficients"] == expected


def test_omodul_without_lesson_json(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = _run("C3H8 + O2 -> CO2 + H2O", out, write_lesson_json=False)
    assert result["status"] == "completed"
    assert "report_path" not in result
    assert result["decision_trail"]["path"] is None
    assert not out.exists()


@pytest.mark.parametrize(
    "eq",
    ["Xx + O2 -> XxO2", "H2 + O2 -> H2O2 + H2O", "Zn + HCl -> ZnCl2", "Na + H2O -> NaOH"],
)
def test_omodul_fails_cleanly(eq: str, tmp_path: Path) -> None:
    result = _run(eq, tmp_path)
    assert result["status"] == "failed"
    assert result["error"]["type"] == "ValueError"
    assert result["fingerprint"]
    assert not list(tmp_path.glob("*.json"))


def test_omodul_fails_when_independent_check_disagrees(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = lesson_mod.balance_equation

    def corrupted(spec: ReactionSpec):  # type: ignore[no-untyped-def]
        sol = real(spec)
        return sol.model_copy(update={"coefficients": [1, 2, 2, 3]})

    monkeypatch.setattr(lesson_mod, "balance_equation", corrupted)
    events: list[dict] = []
    result = equation_balancing_lesson(
        EquationBalancingLessonConfig(),
        EquationBalancingLessonInput(spec=_spec("Fe2O3 + CO -> Fe + CO2")),
        tmp_path,
        on_step=events.append,
    )
    assert result["status"] == "failed"
    assert "independent conservation check failed" in result["error"]["message"]
    assert events[-1]["event"] == "cross_checked" and events[-1]["ok"] is False
    assert not list(tmp_path.glob("equation_balancing_lesson_*.json"))


def test_on_step_callback_receives_each_step(tmp_path: Path) -> None:
    seen: list[str] = []
    equation_balancing_lesson(
        EquationBalancingLessonConfig(write_lesson_json=False),
        EquationBalancingLessonInput(spec=_spec(KNOWN[0][0])),
        tmp_path,
        on_step=lambda e: seen.append(e["event"]),
    )
    assert seen == ["spec_received", "balanced", "cross_checked"]


def test_fingerprint_is_deterministic(tmp_path: Path) -> None:
    a = _run(KNOWN[1][0], tmp_path, write_lesson_json=False)
    b = _run(KNOWN[1][0], tmp_path, write_lesson_json=False)
    c = _run(KNOWN[2][0], tmp_path, write_lesson_json=False)
    assert a["fingerprint"] == b["fingerprint"] != c["fingerprint"]
    assert a["decision_trail"]["run_id"] != b["decision_trail"]["run_id"]
