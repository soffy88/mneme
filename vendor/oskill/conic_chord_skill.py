"""
圆锥曲线过定点弦解题 Skill（oskill 层）
=========================================

组合 ≥2 个 oprim 原语，把一份结构化题目 ``AnalyticGeometrySpec`` 解成：
精确答案（区间 / 区间并 / 定值）+ 分步解析（MathJax LaTeX）+ 交互画板数据。
全部数值来自 oprim 的 sympy 精确计算（单一数据源）。

依赖 oprim 原语（oprim.conic_analysis）：
- parse_exact_number / build_conic / chord_vieta / horizontal_line_meets_twice
- line_param_through / dot_product_expr / chord_length_sq_expr / triangle_area_sq_expr
- constant_in_m / range_over_m / sqrt_range / conic_latex_expr

输出的 ``board_data`` 与 edulab ``template/board.html`` 的数据岛兼容：模板中
``<script id="lesson-data" type="application/json">__LESSON_DATA__</script>``，
占位符为 **``__LESSON_DATA__``**（同 edulab ``scripts/generate.py`` 的 ``PLACEHOLDER``），
数据为 ``{"lesson": {...}, "steps": [...], "board": {...}}`` 三段（见 edulab
``references/problem-schema.md``）。本层不做 IO；渲染（Layer 4）替换占位符时须把 JSON
中的 ``<`` 转义为 ``\\u003c``，防止 ``</script>`` 截断数据岛。

画板约定：参数为倾斜角 θ（``line_through_angle`` 过定点），``intersect_line_conic``
给出 A、B；目标量读数 ``id`` 供 ``rangeBar.of`` / ``constant.of`` 跟踪。无界区间在
``rangeBar`` 上以有限的显示上 / 下限代替（``label`` 仍是精确区间）。

来源：题型与画板结构派生自 wy51ai/edulab ``skills/edu-analytic-geometry/scripts/generate.py``
（commit 6a9c8766061ca7101d10bab6fe3af716ec47bb07，Apache-2.0，Copyright 2026 WY (@akokoi1)），
已由"每题一个 build_*"泛化为按 spec 自动出题面、步骤与画板。
"""

from __future__ import annotations

import math
import re
from typing import Any

import sympy as sp
from pydantic import BaseModel

from oprim.conic_analysis import (
    TARGETS_NEEDING_VERTEX,
    AnalyticGeometrySpec,
    ChordVieta,
    ConicData,
    build_conic,
    chord_length_sq_expr,
    chord_vieta,
    constant_in_m,
    dot_product_expr,
    horizontal_line_meets_twice,
    conic_latex_expr,
    line_param_through,
    parse_exact_number,
    range_over_m,
    sqrt_range,
    triangle_area_sq_expr,
)

m = sp.symbols("m", real=True)
y = sp.symbols("y", real=True)


class ConicStep(BaseModel):
    title: str
    content: str  # HTML 段落，内联 $…$ / 独立 $$…$$


class AnswerPiece(BaseModel):
    lo: float | None  # None = −∞
    hi: float | None  # None = +∞
    lo_closed: bool
    hi_closed: bool


class ConicChordSolution(BaseModel):
    """解题结果（可 JSON 序列化）。"""

    target: str
    answer_kind: str  # "range" | "constant"
    answer_latex: str  # 区间（并）或定值，不含 $
    answer_label: str
    answer_pieces: list[AnswerPiece]
    answer_lo: float | None
    answer_hi: float | None
    constant_value: float | None
    title: str  # 自动生成的中文题面（纯文本）
    problem_html: str
    expression_latex: str  # 目标量（或其平方）关于 m 的表达式
    valid_m_latex: str
    conic_floats: dict[str, float]  # kind 之外的 a / b / p（浮点，供独立复核）
    conic_kind: str
    through: list[float]
    vertex: list[float] | None
    steps: list[ConicStep]
    board_data: dict[str, Any]


_KIND_ZH = {"ellipse": "椭圆", "hyperbola": "双曲线", "parabola": "抛物线"}
_SUP2 = "²"


def _plain(expr: sp.Expr) -> str:
    """题面纯文本数字：2*sqrt(3) → 2√3，3/2 保持。"""
    text = str(sp.nsimplify(expr)).replace("*", "")
    return re.sub(r"sqrt\((\d+)\)", r"√\1", text)


def _plain_eq(conic: ConicData) -> str:
    if conic.kind == "parabola":
        k = sp.nsimplify(2 * conic.p)
        return f"y{_SUP2}={'' if k == 1 else _plain(k)}x"

    def term(var: str, sq: sp.Expr) -> str:
        sq = sp.nsimplify(sq)
        return f"{var}{_SUP2}" if sq == 1 else f"{var}{_SUP2}/{_plain(sq)}"

    op = "+" if conic.kind == "ellipse" else "−"
    return f"{term('x', conic.a**2)}{op}{term('y', conic.b**2)}=1"


def _pt_plain(name: str, xy: tuple[sp.Expr, sp.Expr]) -> str:
    return f"{name}({_plain(xy[0])},{_plain(xy[1])})"


def _pt_tex(name: str, xy: tuple[sp.Expr, sp.Expr]) -> str:
    return rf"{name}\left({conic_latex_expr(xy[0])},\ {conic_latex_expr(xy[1])}\right)"


def _f(expr: sp.Expr) -> float:
    return float(sp.N(expr))


def _coef_tex(coef: sp.Expr, var: str) -> str:
    """二次方程一项：系数为和式时加括号，±1 折叠。返回带符号前缀的片段（首项不带 +）。"""
    coef = sp.expand(coef)
    if coef == 0:
        return ""
    if var and coef == 1:
        return "+" + var
    if var and coef == -1:
        return "-" + var
    body = sp.latex(coef)
    if isinstance(coef, sp.Add):
        return r"+\left(" + body + r"\right)" + var
    if body.startswith("-"):
        return body + var
    return "+" + body + var


def _shift_prod(var: str, val: sp.Expr) -> str:
    """(x_1 − a)(x_2 − a) 的 LaTeX；a=0 时折叠为 x_1x_2。"""
    if val == 0:
        return f"{var}_1{var}_2"
    sign = "-" if val > 0 else "+"
    a = conic_latex_expr(abs(val))
    return f"({var}_1{sign}{a})({var}_2{sign}{a})"


def _quad_tex(chord: ChordVieta) -> str:
    s = _coef_tex(chord.qa, "y^{2}") + _coef_tex(chord.qb, "y") + _coef_tex(chord.qc, "")
    return s.removeprefix("+") + "=0"


def _nice(expr: sp.Expr, *, prefer_apart: bool) -> sp.Expr:
    """展示用化简：数量积优先部分分式（如 −3 + 19/(3m²+4)），弦长 / 面积优先因式分解。"""
    try:
        cand = sp.apart(expr, m) if prefer_apart else sp.factor(expr)
    except (sp.PolynomialError, NotImplementedError):
        cand = sp.factor(expr)
    return cand


def _where_zh(at: dict[str, Any], *, horizontal_reason: str) -> str:
    k = at["kind"]
    if k == "vertical":
        return "当 $m=0$（竖直线）时取到"
    if k == "critical":
        return f"在驻点 $m={at['m']}$ 处取到"
    if k == "horizontal":
        return ("当直线为水平线（$m\\to\\infty$）时取到" if at["attained"]
                else f"当 $m\\to\\infty$ 时趋近，但{horizontal_reason}，取不到")
    if k == "boundary":
        return f"当 $m\\to {at['m']}$ 时趋近（该直线不构成所需图形），取不到"
    return "无界"


def _view(points: list[tuple[float, float]], conic: ConicData) -> dict[str, list[float]]:
    if conic.kind == "ellipse":
        xs, ys = [-_f(conic.a), _f(conic.a)], [-_f(conic.b), _f(conic.b)]
    elif conic.kind == "hyperbola":
        c = _f(conic.c)
        xs, ys = [-c - _f(conic.a), c + _f(conic.a)], [-1.6 * _f(conic.b), 1.6 * _f(conic.b)]
    else:
        p = _f(conic.p)
        xs, ys = [-p, 4 * p], [-2.5 * p, 2.5 * p]
    xs += [q[0] for q in points]
    ys += [q[1] for q in points]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    mx, my = 0.25 * w + 0.4, 0.25 * h + 0.4
    x_rng = [round(min(xs) - mx, 3), round(max(xs) + mx, 3)]
    y_rng = [round(min(ys) - my, 3), round(max(ys) + my, 3)]
    # 让纵横比不至于太扁（引擎按视窗自适应缩放）
    span_x, span_y = x_rng[1] - x_rng[0], y_rng[1] - y_rng[0]
    if span_y < span_x / 1.6:
        pad = (span_x / 1.6 - span_y) / 2
        y_rng = [round(y_rng[0] - pad, 3), round(y_rng[1] + pad, 3)]
    return {"xRange": x_rng, "yRange": y_rng}


def _line_valid_at(chord: ChordVieta, theta_deg: float, horizontal_ok: bool) -> bool:
    if abs(theta_deg % 180) < 1e-9:
        return horizontal_ok
    mv = sp.nsimplify(1 / math.tan(math.radians(theta_deg)), rational=True, tolerance=1e-12)
    qa = sp.N(chord.qa.subs(m, mv))
    disc = sp.N(chord.disc.subs(m, mv))
    return abs(qa) > 1e-9 and disc > 1e-9


def solve_conic_chord(spec: AnalyticGeometrySpec) -> ConicChordSolution:
    """把一道"过定点动弦"圆锥曲线题解成精确答案 + 分步解析 + 交互画板。

    纯算法、stateless、不持久化，故为同步函数。参数非法或构型退化时抛 ``ValueError``。
    """
    q = spec.query
    conic = build_conic(spec.conic)
    through = (parse_exact_number(q.through[0]), parse_exact_number(q.through[1]))
    needs_vertex = q.target in TARGETS_NEEDING_VERTEX
    if needs_vertex and q.vertex is None:
        raise ValueError(f"{q.target} needs a vertex point")
    if not needs_vertex and q.vertex is not None:
        raise ValueError(f"{q.target} takes no vertex point")
    vertex = None if q.vertex is None else (parse_exact_number(q.vertex[0]), parse_exact_number(q.vertex[1]))

    chord = chord_vieta(conic, through=through)
    horizontal_ok = horizontal_line_meets_twice(conic, through=through)
    excluded: list[sp.Expr] = []
    horizontal_reason = "水平线与 $C$ 不交于两点（不构成弦）"
    if conic.kind == "parabola":
        horizontal_reason = "水平线与抛物线的对称轴平行，只有一个交点（不构成弦）"
    if q.target == "triangle_area":
        assert vertex is not None
        mv = line_param_through(through, point=vertex)  # 重合抛 ValueError
        if mv is None:
            horizontal_ok = False
            horizontal_reason = "水平线经过顶点，三点共线，不构成三角形"
        else:
            excluded.append(mv)

    # ── 点命名 ──
    zero = sp.Integer(0)
    focus_names = {k: v for k, v in conic.foci.items()}
    th_name = "P"
    for v in focus_names.values():
        if sp.simplify(v[0] - through[0]) == 0 and sp.simplify(v[1] - through[1]) == 0:
            th_name = "F"
    if through == (zero, zero):
        th_name = "O"
    v_name = None
    if vertex is not None:
        if vertex == through:
            v_name = th_name
        else:
            v_name = "O" if vertex == (zero, zero) else "M"

    if q.target == "triangle_area" and not horizontal_ok and v_name:
        horizontal_reason = horizontal_reason.replace("顶点", f"点 ${v_name}$")

    # ── 目标量表达式与范围 ──
    vec = (rf"\overrightarrow{{{v_name}A}}\cdot\overrightarrow{{{v_name}B}}" if v_name else "")
    if q.target in ("dot_product", "fixed_value_dot"):
        assert vertex is not None
        expr = dot_product_expr(chord, vertex=vertex)
        rng = range_over_m(expr, chord=chord, horizontal_valid=horizontal_ok)
        target_tex, sq_tex = vec, vec
        answer_label = f"向量数量积 {v_name}A·{v_name}B 的{'定值' if q.target == 'fixed_value_dot' else '取值范围'}"
        ask_html = (f"求证 ${vec}$ 为定值，并求出该定值。" if q.target == "fixed_value_dot"
                    else f"求 ${vec}$ 的取值范围。")
        ask_plain = (f"求证 {v_name}A·{v_name}B（向量）为定值，并求出该定值。" if q.target == "fixed_value_dot"
                     else f"求 {v_name}A·{v_name}B（向量数量积）的取值范围。")
        if q.target == "fixed_value_dot":
            is_const, _ = constant_in_m(expr)
            if not is_const or rng.constant is None:
                raise ValueError("MA·MB is not a fixed value for this configuration")
        final = rng
    elif q.target == "chord_length":
        expr = chord_length_sq_expr(chord)
        rng = range_over_m(expr, chord=chord, horizontal_valid=horizontal_ok)
        final = sqrt_range(rng)
        target_tex, sq_tex = "|AB|", "|AB|^2"
        answer_label = "弦长 |AB| 的取值范围"
        ask_html, ask_plain = "求弦长 $|AB|$ 的取值范围。", "求弦长 |AB| 的取值范围。"
    else:
        assert vertex is not None
        expr = triangle_area_sq_expr(chord, vertex=vertex)
        rng = range_over_m(expr, chord=chord, horizontal_valid=horizontal_ok, excluded_m=excluded)
        final = sqrt_range(rng)
        target_tex, sq_tex = rf"S_{{\triangle {v_name}AB}}", rf"S_{{\triangle {v_name}AB}}^2"
        answer_label = f"△{v_name}AB 面积的取值范围"
        ask_html = rf"求 $\triangle {v_name}AB$ 面积的取值范围。"
        ask_plain = f"求 △{v_name}AB 面积的取值范围。"

    is_constant = final.constant is not None
    answer_latex = final.latex

    # ── 题面 ──
    kind_zh = _KIND_ZH[conic.kind]
    given_v = ""
    if vertex is not None and v_name != th_name:
        given_v = f"，点 ${_pt_tex(v_name, vertex)}$" if v_name != "O" else "，$O$ 为坐标原点"
    focus_note = "（焦点）" if th_name == "F" else ""
    problem_html = (
        "<p class='font-medium text-slate-800'>【题目】</p>"
        f"<p>已知{kind_zh} $C:\\,{conic.eq_latex}${given_v}，过点 ${_pt_tex(th_name, through)}${focus_note}"
        f"的直线 $l$ 与 $C$ 交于 $A,B$ 两点。{ask_html}</p>"
    )
    given_v_plain = ""
    if vertex is not None and v_name != th_name:
        given_v_plain = f"，点 {_pt_plain(v_name, vertex)}" if v_name != "O" else "，O 为坐标原点"
    title = (f"已知{kind_zh} C: {_plain_eq(conic)}{given_v_plain}，过点 {_pt_plain(th_name, through)}{focus_note}"
             f"的直线 l 与 C 交于 A、B 两点，{ask_plain}")

    # ── 步骤 ──
    x0, y0 = through
    c_tex = conic_latex_expr(chord.c)
    line_tex = rf"x=my{'' if c_tex.startswith('-') else '+'}{c_tex}" if chord.c != 0 else "x=my"
    if y0 != 0:
        x0_tex = "" if x0 == 0 else (conic_latex_expr(x0) if x0 < 0 else "+" + conic_latex_expr(x0))
        line_tex = rf"x=m\left(y{'-' if y0 > 0 else '+'}{conic_latex_expr(abs(y0))}\right){x0_tex}"
    if horizontal_ok:
        h_note = f"水平线 $y={conic_latex_expr(y0)}$ 与 $C$ 交于两点，是合法的弦（对应 $m\\to\\infty$）。"
    else:
        h_note = f"水平线 $y={conic_latex_expr(y0)}$（对应 $m\\to\\infty$）：{horizontal_reason}，应排除。"
    steps: list[ConicStep] = [ConicStep(
        title="设直线",
        content=(f"<p>设直线 $l:\\,{line_tex}$，其中 $m=\\cot\\theta$（$\\theta$ 为倾斜角）。"
                 "这样竖直线对应 $m=0$，无需讨论斜率是否存在。</p>"
                 f"<p>{h_note}</p>"),
    )]

    excl_note = ""
    if excluded:
        excl_note = f"另外直线不能经过点 ${v_name}$（否则三点共线），即 $m\\ne {conic_latex_expr(excluded[0])}$。"
    steps.append(ConicStep(
        title="联立方程",
        content=(f"<p>代入 $C:\\,{conic.eq_latex}$，消去 $x$ 整理得</p>"
                 f"$$ {_quad_tex(chord)} $$"
                 f"<p>要有两个不同交点，需二次项系数不为 $0$ 且 $\\Delta>0$：</p>"
                 f"$$ \\Delta={sp.latex(sp.factor(chord.disc))} $$"
                 f"<p>{excl_note}合法直线对应 ${rng.valid_m_latex}$。</p>"),
    ))

    vieta = (f"$$ y_1+y_2={conic_latex_expr(chord.y_sum)},\\qquad y_1y_2={conic_latex_expr(chord.y_prod)} $$")
    if q.target in ("dot_product", "fixed_value_dot"):
        xi_tex = line_tex.replace("x=", "x_i=", 1).replace("y", "y_i")
        vieta += (f"<p>由 ${xi_tex}$ 得</p>"
                  f"$$ x_1+x_2={conic_latex_expr(chord.x_sum)},\\qquad x_1x_2={conic_latex_expr(chord.x_prod)} $$")
    steps.append(ConicStep(title="韦达定理", content=f"<p>设 $A(x_1,y_1),\\ B(x_2,y_2)$，由韦达定理</p>{vieta}"))

    nice = _nice(expr, prefer_apart=q.target in ("dot_product", "fixed_value_dot"))
    expr_tex = conic_latex_expr(nice) if is_constant else sp.latex(nice)
    if q.target in ("dot_product", "fixed_value_dot"):
        assert vertex is not None
        formula = f"{vec}={_shift_prod('x', vertex[0])}+{_shift_prod('y', vertex[1])}"
        content = f"<p>${formula}$，代入韦达量化简：</p>$$ {vec}={expr_tex} $$"
    elif q.target == "chord_length":
        content = ("<p>弦长公式 $|AB|^2=(1+m^2)\\left[(y_1+y_2)^2-4y_1y_2\\right]$，代入得</p>"
                   f"$$ |AB|^2={expr_tex} $$")
    else:
        assert vertex is not None
        d_lin = sp.expand(vertex[0] - m * vertex[1] - chord.c)
        d_num = conic_latex_expr(abs(d_lin) if not d_lin.free_symbols else d_lin)
        content = (f"<p>$S=\\dfrac12|AB|\\cdot d$，点 ${v_name}$ 到 $l$ 的距离 "
                   f"$d=\\dfrac{{\\left|{d_num}\\right|}}{{\\sqrt{{1+m^2}}}}$，$1+m^2$ 约去得</p>"
                   f"$$ {sq_tex}=\\dfrac14\\left[(y_1+y_2)^2-4y_1y_2\\right]\\left({d_num}\\right)^2={expr_tex} $$")
    steps.append(ConicStep(title="目标量的表达式", content=content))

    if is_constant:
        steps.append(ConicStep(
            title="求定值",
            content=(f"<p>上式与 $m$ 无关（对 $m$ 求导恒为 $0$），且对每条合法直线（${rng.valid_m_latex}$"
                     f"{'及水平线' if horizontal_ok else ''}）都成立，故为定值：</p>"
                     "<div class='text-center py-3 bg-emerald-50 border border-emerald-100 rounded-xl text-emerald-900 font-bold'>"
                     f"$$ {target_tex}={answer_latex} $$</div>"),
        ))
    else:
        lines = []
        for piece in rng.pieces:
            for label, val, at in (("下端", piece.lo, piece.lo_at), ("上端", piece.hi, piece.hi_at)):
                if val in (sp.oo, -sp.oo):
                    lines.append(f"<li>{label}：${conic_latex_expr(val)}$（无界）</li>")
                else:
                    lines.append(f"<li>{label} ${conic_latex_expr(val)}$：{_where_zh(at, horizontal_reason=horizontal_reason)}</li>")
        sq_line = ""
        if q.target in ("chord_length", "triangle_area"):
            sq_line = f"<p>于是 ${sq_tex}\\in {rng.latex}$，开方（单调）得：</p>"
        steps.append(ConicStep(
            title="求取值范围",
            content=("<p>在合法直线集合上考察驻点、竖直线、水平线及边界极限：</p>"
                     f"<ul class='list-disc pl-5 space-y-1'>{''.join(lines)}</ul>{sq_line}"
                     "<div class='text-center py-3 bg-emerald-50 border border-emerald-100 rounded-xl text-emerald-900 font-bold'>"
                     f"$$ {target_tex}\\in {answer_latex} $$</div>"),
        ))
    concl = (f"<p>所以 ${target_tex}$ 为定值 ${answer_latex}$。</p>" if is_constant
             else f"<p>所以 ${target_tex}$ 的取值范围是 ${answer_latex}$。</p>")
    steps.append(ConicStep(title="结论", content=concl))

    # ── 答案浮点 ──
    pieces = [
        AnswerPiece(
            lo=None if p.lo == -sp.oo else _f(p.lo),
            hi=None if p.hi == sp.oo else _f(p.hi),
            lo_closed=p.lo_closed, hi_closed=p.hi_closed,
        )
        for p in final.pieces
    ]

    # ── 画板 ──
    th_xy = (_f(through[0]), _f(through[1]))
    pts: dict[str, Any] = {}
    board_pts = [th_xy]
    pts[th_name] = {"xy": list(th_xy), "color": "given", "label": _pt_plain(th_name, through), "emphasis": True}
    if vertex is not None and v_name != th_name:
        v_xy = (_f(vertex[0]), _f(vertex[1]))
        board_pts.append(v_xy)
        pts[v_name] = {"xy": list(v_xy), "color": "vecA" if q.target != "triangle_area" else "fixed",
                       "label": _pt_plain(v_name, vertex) if v_name != "O" else "O", "emphasis": v_name != "O"}
    for fname, fxy in focus_names.items():
        taken = [through] + ([vertex] if vertex is not None else [])
        if any(sp.simplify(fxy[0] - t[0]) == 0 and sp.simplify(fxy[1] - t[1]) == 0 for t in taken):
            continue
        key = {"F1": "F₁", "F2": "F₂", "F": "F"}[fname]
        if key in pts or fname in pts:
            continue
        pts[fname] = {"xy": [_f(fxy[0]), _f(fxy[1])], "color": "point", "label": key}

    standard = next((t for t in (45, 60, 30, 75, 120, 135, 150, 90, 15, 165, 0) if _line_valid_at(chord, t, horizontal_ok)), 90)
    derived: list[dict[str, Any]] = [
        {"type": "line_through_angle", "name": "l", "point": th_name, "angle": "@param", "color": "line"},
        {"type": "intersect_line_conic", "name": ["A", "B"], "line": "l", "conic": "C", "colors": ["ptA", "ptB"]},
    ]
    readouts: list[dict[str, Any]] = [
        {"id": "k", "label": "直线斜率 k", "type": "slope", "of": "l"},
        {"id": "A", "label": "交点 A", "type": "coord", "of": "A", "color": "ptA"},
        {"id": "B", "label": "交点 B", "type": "coord", "of": "B", "color": "ptB"},
    ]
    legend = [{"color": "line", "text": "动直线 l"}]
    if q.target in ("dot_product", "fixed_value_dot"):
        derived += [
            {"type": "vector", "name": "vA", "from": v_name, "to": "A", "color": "vecA"},
            {"type": "vector", "name": "vB", "from": v_name, "to": "B", "color": "vecB"},
        ]
        readouts.append({"id": "target", "label": f"数量积 ${vec}$", "type": "dot", "a": "vA", "b": "vB", "highlight": True})
        legend += [{"color": "vecA", "text": f"向量 {v_name}A"}, {"color": "vecB", "text": f"向量 {v_name}B"}]
    elif q.target == "chord_length":
        derived.append({"type": "segment", "name": "AB", "a": "A", "b": "B", "color": "line2"})
        readouts.append({"id": "target", "label": "弦长 $|AB|$", "type": "length", "a": "A", "b": "B", "highlight": True})
    else:
        derived.append({"type": "polygon", "name": "tri", "pts": [v_name, "A", "B"], "color": "area", "stroke": "line2"})
        readouts.append({"id": "len", "label": "弦长 $|AB|$", "type": "length", "a": "A", "b": "B"})
        readouts.append({"id": "target", "label": f"${target_tex}$", "type": "area_triangle",
                         "pts": [v_name, "A", "B"], "highlight": True})
        legend.append({"color": "area", "text": f"△{v_name}AB"})

    conic_board = dict(conic.board)
    conic_board.update({"name": "C", "color": "curve", "label": f"C: {_plain_eq(conic)}"})
    board: dict[str, Any] = {
        "view": _view(board_pts, conic),
        "conics": [conic_board],
        "points": pts,
        "param": {"name": "θ", "label": "直线 $l$ 的倾斜角 $\\theta$", "min": 0, "max": 180, "step": 0.5,
                  "value": standard, "unit": "°", "standard": standard,
                  "ticks": ["0° (水平)", "90° (竖直)", "180°"]},
        "derived": derived,
        "readouts": readouts,
        "legend": legend,
    }
    if is_constant:
        board["constant"] = {"of": "target", "label": f"${answer_latex}$"}
    else:
        finite = [v for pc in pieces for v in (pc.lo, pc.hi) if v is not None]
        span = max([1.0, *[abs(v) for v in finite]])
        lo_bar = pieces[0].lo if pieces[0].lo is not None else min(finite) - 2 * span
        hi_bar = pieces[-1].hi if pieces[-1].hi is not None else max(finite) + 2 * span
        board["rangeBar"] = {"of": "target", "min": round(lo_bar, 6), "max": round(hi_bar, 6), "label": f"${answer_latex}$"}

    short_title = {
        "dot_product": f"{_KIND_ZH[conic.kind]}过定点弦的数量积范围",
        "fixed_value_dot": f"{_KIND_ZH[conic.kind]}过定点弦的数量积定值",
        "chord_length": f"{_KIND_ZH[conic.kind]}过定点的弦长范围",
        "triangle_area": f"{_KIND_ZH[conic.kind]}中三角形面积的范围",
    }[q.target]
    answer_disp = (f"${target_tex}={answer_latex}$" if is_constant else f"${target_tex}\\in {answer_latex}$")
    board_data = {
        "lesson": {
            "language": spec.language,
            "title": short_title,
            "problem": problem_html,
            "answerLabel": answer_label,
            "answer": answer_disp,
        },
        "steps": [s.model_dump() for s in steps],
        "board": board,
    }

    floats = {k: v for k, v in conic.board.items() if k in ("a", "b", "p")}
    return ConicChordSolution(
        target=q.target,
        answer_kind="constant" if is_constant else "range",
        answer_latex=answer_latex,
        answer_label=answer_label,
        answer_pieces=pieces,
        answer_lo=pieces[0].lo,
        answer_hi=pieces[-1].hi,
        constant_value=_f(final.constant) if is_constant else None,
        title=title,
        problem_html=problem_html,
        expression_latex=conic_latex_expr(expr),
        valid_m_latex=rng.valid_m_latex,
        conic_floats=floats,
        conic_kind=conic.kind,
        through=[th_xy[0], th_xy[1]],
        vertex=None if vertex is None else [_f(vertex[0]), _f(vertex[1])],
        steps=steps,
        board_data=board_data,
    )


__all__ = ["AnswerPiece", "ConicChordSolution", "ConicStep", "solve_conic_chord"]
