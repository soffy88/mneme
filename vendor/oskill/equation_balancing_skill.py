"""
化学方程式配平 Skill（oskill 层）
=================================

组合 ≥2 个 oprim 原语，把一份结构化反应 ``ReactionSpec`` 解成：
最小正整数系数 + 配平后的方程式（LaTeX / Unicode 纯文本）+ 原子（电荷）守恒表 +
各物质摩尔质量 + 中文分步解析（HTML，内联 ``$…$`` / 独立 ``$$…$$`` LaTeX）。
全部数值来自 oprim 的确定性计算。

依赖 oprim 原语（oprim.chemical_equation）：
- parse_formula / composition_matrix / balance_coefficients
- atom_conservation_table / molar_mass / formula_latex / format_equation_latex

无状态、无 IO，同步函数。

来源：派生自 wy51ai/edulab ``skills/edu-chem-reaction``（lib/reaction_kernel.py、
scripts/generate.py，commit 6a9c8766061ca7101d10bab6fe3af716ec47bb07，Apache-2.0，
Copyright 2026 WY (@akokoi1)）。已改写为 3O oskill 形态，去掉 3D 动画装配，
新增分步配平解析。
"""

from __future__ import annotations

import html
from fractions import Fraction
from typing import Any

from pydantic import BaseModel

from oprim.chemical_equation import (
    CHARGE_ROW,
    ConservationRow,
    ReactionSpec,
    atom_conservation_table,
    balance_coefficients,
    composition_matrix,
    format_equation_latex,
    formula_latex,
    molar_mass,
    parse_formula,
)


class ChemStep(BaseModel):
    title: str
    content: str  # HTML 段落，内联 $…$ / 独立 $$…$$


class EquationBalancingSolution(BaseModel):
    """配平结果（可 JSON 序列化）。"""

    reactants: list[str]  # 规范化学式
    products: list[str]
    coefficients: list[int]  # 与 reactants + products 顺序对应
    equation_latex: str
    equation_text: str  # Unicode 下标 / 上标，如 "2KMnO₄ + 16HCl → …"
    conservation: list[ConservationRow]
    molar_masses: dict[str, float | None]  # 元素不在教材原子量表中时为 None
    title: str
    steps: list[ChemStep]
    lesson_data: dict[str, Any]


_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_SUP = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")


def _plain(formula: str) -> str:
    """规范化学式 → Unicode：下标数字、上标电荷，结晶水系数保持正常数字。"""
    body, _, charge = formula.partition("^")
    out: list[str] = []
    prev = ""
    for ch in body:
        if ch.isdigit() and (prev.isalpha() or prev in ")]" or (out and out[-1] in "₀₁₂₃₄₅₆₇₈₉" and prev.isdigit())):
            out.append(ch.translate(_SUB))
        else:
            out.append(ch)
        prev = ch
    return "".join(out) + charge.translate(_SUP)


def _side_text(coefs: list[int], species: list[str]) -> str:
    return " + ".join(f"{c if c > 1 else ''}{_plain(s)}" for c, s in zip(coefs, species, strict=True))


def _x(i: int) -> str:
    return f"x_{{{i + 1}}}"


def _linear(terms: list[tuple[int, int]]) -> str:
    """[(系数, 未知数下标)] → ``2x_{1} - x_{2}``（系数 1 省略，0 跳过）。"""
    parts: list[str] = []
    for k, i in terms:
        if k == 0:
            continue
        mag = "" if abs(k) == 1 else str(abs(k))
        if not parts:
            parts.append(f"{'-' if k < 0 else ''}{mag}{_x(i)}")
        else:
            parts.append(f" {'-' if k < 0 else '+'} {mag}{_x(i)}")
    return "".join(parts) or "0"


def _signed(v: int) -> str:
    return f"+{v}" if v > 0 else str(v)


def balance_equation(spec: ReactionSpec) -> EquationBalancingSolution:
    """配平一个化学 / 离子方程式并给出分步解析。

    纯算法、stateless、不持久化，故为同步函数。化学式非法、元素只出现在一侧、
    无法配平或多解时抛 ``ValueError``（消息为中文原因）。
    """
    parsed = [parse_formula(f) for f in spec.reactants + spec.products]
    n = len(spec.reactants)
    reactants = [p.formula for p in parsed[:n]]
    products = [p.formula for p in parsed[n:]]
    species = reactants + products

    matrix = composition_matrix(parsed, n_reactants=n)
    coefs = balance_coefficients(matrix)
    table = atom_conservation_table(matrix, coefficients=coefs)
    eq_tex = format_equation_latex(coefs, reactants=reactants, products=products)
    eq_text = f"{_side_text(coefs[:n], reactants)} → {_side_text(coefs[n:], products)}"
    tex = {s: formula_latex(s) for s in species}

    masses: dict[str, float | None] = {}
    for p in parsed:
        try:
            masses[p.formula] = molar_mass(p)
        except ValueError:
            masses[p.formula] = None

    ones = [1] * len(species)
    raw_text = f"{_side_text(ones[:n], reactants)} → {_side_text(ones[n:], products)}"
    title = f"配平化学方程式：{raw_text}"
    has_charge = matrix.rows[-1] == CHARGE_ROW

    # 1. 写出各物质组成
    comp_lines = []
    for i, p in enumerate(parsed):
        atoms = "，".join(f"{el} {k}" for el, k in p.counts.items())
        charge = f"，电荷 ${_signed(p.charge)}$" if p.charge else ""
        side = "反应物" if i < n else "生成物"
        comp_lines.append(f"<li>{side} ${tex[p.formula]}$（系数设为 ${_x(i)}$）：{html.escape(atoms)}{charge}</li>")
    step1 = ChemStep(
        title="写出各物质组成",
        content=(
            "<p>设各物质的化学计量数依次为 "
            + "、".join(f"${_x(i)}$" for i in range(len(species)))
            + "，逐一数出每个化学式中各元素的原子个数"
            + ("与离子电荷" if has_charge else "")
            + "：</p><ul>"
            + "".join(comp_lines)
            + "</ul>"
        ),
    )

    # 2. 列原子守恒方程组
    eqs = []
    for name, row in zip(matrix.rows, matrix.matrix, strict=True):
        left = _linear([(row[j], j) for j in range(n)])
        right = _linear([(row[j], j) for j in range(n, len(species))])
        label = r"\text{电荷}" if name == CHARGE_ROW else rf"\mathrm{{{name}}}"
        eqs.append(f"{label}:\\ {left} = {right}")
    step2 = ChemStep(
        title="列原子守恒方程组",
        content=(
            "<p>化学反应前后每种元素的原子个数不变"
            + ("；离子方程式还要求反应前后电荷总数相等" if has_charge else "")
            + "，据此列方程组：</p>"
            + "$$\\begin{cases}"
            + r" \\ ".join(eqs)
            + r"\end{cases}$$"
        ),
    )

    # 3. 求解最小正整数解
    base = coefs[0]
    rel = [Fraction(c, base) for c in coefs]
    rel_tex = ",\\ ".join(
        f"{_x(i)} = " + (str(r.numerator) if r.denominator == 1 else f"\\tfrac{{{r.numerator}}}{{{r.denominator}}}")
        for i, r in enumerate(rel)
    )
    ratio = " : ".join(str(c) for c in coefs)
    step3 = ChemStep(
        title="求解最小正整数解",
        content=(
            f"<p>方程组有 {len(species)} 个未知数，解空间是一维的，即各系数之比唯一确定。"
            f"令 ${_x(0)} = 1$，解得</p>$${rel_tex}$$"
            + (
                "<p>乘以各分母的最小公倍数并约去公因数，得到最小正整数解：</p>"
                if any(r.denominator != 1 for r in rel)
                else "<p>各值已是互质的正整数，即最小正整数解：</p>"
            )
            + f"$${':'.join(_x(i) for i in range(len(species)))} = {ratio}$$"
        ),
    )

    # 4. 检验守恒
    rows_html = "".join(
        f"<tr><td>{'电荷' if r.row == CHARGE_ROW else html.escape(r.row)}</td>"
        f"<td>{_signed(r.left) if r.row == CHARGE_ROW else r.left}</td>"
        f"<td>{_signed(r.right) if r.row == CHARGE_ROW else r.right}</td>"
        f"<td>{'✓' if r.balanced else '✗'}</td></tr>"
        for r in table
    )
    step4 = ChemStep(
        title="检验守恒",
        content=(
            "<p>把系数代回，逐项统计反应前后的原子" + ("与电荷" if has_charge else "") + "总数：</p>"
            "<table><thead><tr><th>项目</th><th>反应前</th><th>反应后</th><th>守恒</th></tr></thead>"
            f"<tbody>{rows_html}</tbody></table>"
            + ("<p>各项均相等，配平正确。</p>" if all(r.balanced for r in table) else "<p>存在不相等项！</p>")
        ),
    )

    # 5. 结论
    mass_items = "".join(
        f"<li>${tex[s]}$：$M = {masses[s]:g}\\ \\mathrm{{g/mol}}$</li>"
        if masses[s] is not None
        else f"<li>${tex[s]}$：含中学原子量表以外的元素，未计算</li>"
        for s in species
    )
    step5 = ChemStep(
        title="结论",
        content=(
            f"<p>配平后的方程式为</p>$${eq_tex}$$<p>各物质的摩尔质量（按教材相对原子质量）：</p><ul>{mass_items}</ul>"
        ),
    )
    steps = [step1, step2, step3, step4, step5]

    lesson_data = {
        "lesson": {
            "title": title,
            "equation": eq_tex,
            "equationText": eq_text,
            "coefficients": coefs,
            "species": species,
            "language": spec.language,
        },
        "steps": [s.model_dump() for s in steps],
        "conservation": [r.model_dump() for r in table],
        "molarMasses": masses,
    }

    return EquationBalancingSolution(
        reactants=reactants,
        products=products,
        coefficients=coefs,
        equation_latex=eq_tex,
        equation_text=eq_text,
        conservation=table,
        molar_masses=masses,
        title=title,
        steps=steps,
        lesson_data=lesson_data,
    )
