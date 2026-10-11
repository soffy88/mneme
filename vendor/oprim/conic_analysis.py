"""
解析几何（圆锥曲线）确定性计算原语（oprim 层）
=================================================

圆锥曲线方程、联立后的二次方程、韦达量、目标量关于参数 m 的表达式以及
取值范围（含开闭端点判定）全部由 sympy 精确符号运算得出，不依赖 LLM、
不做心算。同一份精确结果同时喂给解题步骤与交互画板，保证"图、解、答"
同源一致。

核心套路：含参直线 ``x = m·y + c``（``c`` 由"过定点"确定），代入圆锥曲线
得关于 y 的二次方程，韦达定理给出 ``y1+y2``、``y1·y2``，把目标量（数量积 /
弦长 / 面积）写成 m 的有理式，再在"合法直线"集合上求其取值范围。

m 的几何含义：直线 ``x = m·y + c`` 的方向为 ``(m, 1)``，即 ``m = cot θ``：
- ``m = 0``  → 竖直线（θ = 90°）
- ``m → ∞`` → 水平线（θ = 0°），是否为合法弦需单独判定
  （椭圆过内点：是；抛物线：水平线与对称轴平行只交一点，**不是**）

3O 范式 oprim 约束：
- 每个公开函数是一次原子计算，公开函数之间互不调用（只共享 ``_`` 私有工具）
- 纯函数：无 IO、无全局状态、无随机；纯计算故为同步函数
- 签名：≤1 个核心位置参数，其余 keyword-only
- 输入输出类型显式（Pydantic 模型 / sympy 对象）

安全：曲线参数与点坐标只接受受限字面量（整数、有限小数、``p/q``、
``k*sqrt(m)``、``k√m/q``，坐标可带符号），绝不对外部字符串调用
``sympy.sympify``（其内部走 ``eval``）。

来源：解析几何内核派生自 wy51ai/edulab
``skills/edu-analytic-geometry/lib/{analytic_kernel,conics}.py``
（commit 6a9c8766061ca7101d10bab6fe3af716ec47bb07，Apache-2.0，
Copyright 2026 WY (@akokoi1)）。已改写为 3O oprim 形态，并新增受限字面量
解析、合法直线集合（判别式 / 二次项系数 / 排除直线）上的分段取值范围与
并集输出、水平线合法性判定、独立浮点复核。
"""

from __future__ import annotations

import itertools
import math
import re
from collections.abc import Sequence
from typing import Any, Literal

import sympy as sp
from pydantic import BaseModel, ConfigDict, Field

# ──────────────────────────────────────────────────────────────────────────────
# 类型
# ──────────────────────────────────────────────────────────────────────────────

ConicKind = Literal["ellipse", "hyperbola", "parabola"]
ChordTarget = Literal["dot_product", "chord_length", "triangle_area", "fixed_value_dot"]
NumberLiteral = int | float | str

MAX_PARAMETER = 1000  # 曲线参数上界（a、b、p）
MAX_COORDINATE = 1000  # 点坐标绝对值上界

TARGETS_NEEDING_VERTEX = frozenset({"dot_product", "triangle_area", "fixed_value_dot"})

x, y = sp.symbols("x y", real=True)
m = sp.symbols("m", real=True)


class ConicSpec(BaseModel):
    """标准位置的圆锥曲线（中心 / 顶点在原点，焦点在 x 轴）。

    - ``ellipse``:   ``x²/a² + y²/b² = 1``，要求 ``a > b > 0``
    - ``hyperbola``: ``x²/a² − y²/b² = 1``，``a, b > 0``
    - ``parabola``:  ``y² = 2px``，``p > 0``
    """

    kind: ConicKind
    a: int | float | str | None = None
    b: int | float | str | None = None
    p: int | float | str | None = None

    model_config = ConfigDict(extra="forbid")


class ChordQuery(BaseModel):
    """所求：过定点 ``through`` 的动直线与曲线交于 A、B，目标量由 ``target`` 决定。

    - ``dot_product``:     ``vertex`` 记为 M，求 ``MA·MB`` 的取值范围
    - ``chord_length``:    求弦长 ``|AB|`` 的取值范围（不需要 ``vertex``）
    - ``triangle_area``:   ``vertex`` 记为 M，求 ``S△MAB`` 的取值范围
    - ``fixed_value_dot``: ``vertex`` 记为 M，证明 ``MA·MB`` 为定值并求之
    """

    through: list[int | float | str] = Field(min_length=2, max_length=2)
    target: ChordTarget
    vertex: list[int | float | str] | None = Field(default=None, min_length=2, max_length=2)

    model_config = ConfigDict(extra="forbid")


class AnalyticGeometrySpec(BaseModel):
    """结构化题目（文字 / 图片 / 随机三入口归一后的中间产物）。"""

    conic: ConicSpec
    query: ChordQuery
    language: Literal["zh-CN"] = "zh-CN"

    model_config = ConfigDict(extra="forbid")


class ConicData(BaseModel):
    """``build_conic`` 的产物：精确几何量 + 画板浮点参数。"""

    kind: ConicKind
    a: Any = None  # sympy.Expr
    b: Any = None
    c: Any = None  # 半焦距
    p: Any = None
    implicit: Any  # 关于 x, y 的隐式表达式（= 0）
    eq_latex: str
    foci: dict[str, tuple[Any, Any]]
    vertices: dict[str, tuple[Any, Any]]
    eccentricity: Any
    directrices: list[Any]  # 准线 x = value 的 value 列表
    asymptote_slopes: list[Any] = Field(default_factory=list)
    board: dict[str, Any]  # 注入 board.conics[*] 的浮点字段

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ChordVieta(BaseModel):
    """直线 ``x = m·y + c`` 与曲线联立后的二次方程 ``qa·y² + qb·y + qc = 0`` 及韦达量。"""

    through: tuple[Any, Any]
    c: Any  # 截距 c(m) = x0 − m·y0
    qa: Any
    qb: Any
    qc: Any
    y_sum: Any
    y_prod: Any
    x_sum: Any
    x_prod: Any
    disc: Any

    model_config = ConfigDict(arbitrary_types_allowed=True)


class RangePiece(BaseModel):
    """取值范围的一段区间。``*_at`` 记录端点在哪种直线处取到 / 趋近。

    ``*_at`` = ``{"kind": vertical|critical|horizontal|boundary|unbounded|constant,
    "m": LaTeX 或 None, "attained": bool}``
    """

    lo: Any
    hi: Any
    lo_closed: bool
    hi_closed: bool
    lo_at: dict[str, Any]
    hi_at: dict[str, Any]

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ValueRange(BaseModel):
    """目标量的取值范围（可能是若干区间的并）。``constant`` 非空表示定值。"""

    pieces: list[RangePiece]
    constant: Any = None
    latex: str
    valid_m_latex: str

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def lo(self) -> Any:
        return self.pieces[0].lo

    @property
    def hi(self) -> Any:
        return self.pieces[-1].hi


class NumericRangeCheck(BaseModel):
    """独立浮点复核结果：按倾斜角密集采样得到的取值范围估计。"""

    pieces: list[tuple[float, float]]
    n_samples: int
    n_valid: int
    sampled_min: float
    sampled_max: float


# ──────────────────────────────────────────────────────────────────────────────
# 私有工具（可被多个公开原语共享；公开原语之间不互相调用）
# ──────────────────────────────────────────────────────────────────────────────

_INT_RE = re.compile(r"^\s*([+-])?\s*(\d{1,4})(?:\s*/\s*(\d{1,4}))?\s*$")
_SQRT_RE = re.compile(
    r"^\s*([+-])?\s*(\d{1,4})?\s*\*?\s*(?:sqrt|√)\s*(?:\(\s*(\d{1,4})\s*\)|(\d{1,4}))\s*(?:/\s*(\d{1,4}))?\s*$"
)
_PREC = 50  # 高精度数值比较位数


def _parse_literal(value: NumberLiteral, *, positive: bool, bound: int) -> sp.Expr:
    """受限字面量 → sympy 精确数。拒绝一切其它写法（不 sympify）。"""
    if isinstance(value, bool):
        raise ValueError("literal must be numeric")  # noqa: TRY004 - 统一以 ValueError 拒绝非法输入
    if isinstance(value, int):
        expr: sp.Expr = sp.Integer(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("literal must be finite")
        expr = sp.Rational(repr(value))
    elif isinstance(value, str):
        if len(value) > 32:
            raise ValueError("literal too long")
        mt = _INT_RE.match(value)
        if mt:
            sign = -1 if mt.group(1) == "-" else 1
            num, den = int(mt.group(2)), int(mt.group(3) or 1)
            if den == 0:
                raise ValueError("zero denominator")
            expr = sign * sp.Rational(num, den)
        else:
            mt = _SQRT_RE.match(value)
            if not mt:
                raise ValueError(f"unsupported literal: {value!r}")
            sign = -1 if mt.group(1) == "-" else 1
            coef = int(mt.group(2) or 1)
            radicand = int(mt.group(3) or mt.group(4))
            den = int(mt.group(5) or 1)
            if den == 0:
                raise ValueError("zero denominator")
            expr = sign * sp.Rational(coef, den) * sp.sqrt(radicand)
    else:
        raise ValueError("literal must be int, float or str")  # noqa: TRY004
    if positive and not (expr > 0):
        raise ValueError("literal must be positive")
    if abs(expr) > bound:
        raise ValueError(f"literal out of range (|v| <= {bound})")
    return sp.nsimplify(expr)


def _simp(expr: sp.Expr) -> sp.Expr:
    return sp.radsimp(sp.simplify(expr))


def _f(expr: sp.Expr) -> float:
    return float(sp.N(expr))


def _hp(expr: sp.Expr) -> sp.Float:
    return sp.N(expr, _PREC)


def _latex(expr: sp.Expr) -> str:
    if expr == sp.oo:
        return r"+\infty"
    if expr == -sp.oo:
        return r"-\infty"
    return sp.latex(_simp(expr))


def _term(numer_latex: str, denom: sp.Expr) -> str:
    """分式项：分母为 1 时折叠为分子本身（x^2/1 → x^2）。"""
    denom = _simp(denom)
    if denom == 1:
        return numer_latex
    return rf"\frac{{{numer_latex}}}{{{sp.latex(denom)}}}"


def _interval_latex(pieces: Sequence[tuple[sp.Expr, sp.Expr, bool, bool]]) -> str:
    parts = []
    for lo, hi, lc, hc in pieces:
        if lo == hi and lc and hc:
            parts.append(rf"\left\{{{_latex(lo)}\right\}}")
            continue
        lb = "[" if lc else "("
        rb = "]" if hc else ")"
        parts.append(rf"\left{lb}{_latex(lo)},\ {_latex(hi)}\right{rb}")
    return r"\cup".join(parts)


def _real_roots(expr: sp.Expr) -> list[sp.Expr]:
    """关于 m 的多项式的全部互异实根（精确）。"""
    expr = sp.expand(expr)
    if expr.free_symbols - {m}:
        raise ValueError("expression must depend on m only")
    if m not in expr.free_symbols:
        return []
    poly = sp.Poly(expr, m)
    if poly.degree() <= 0:
        return []
    try:
        roots = list(dict.fromkeys(poly.real_roots()))
    except (sp.PolynomialError, NotImplementedError, sp.DomainError):
        roots = []
        for r in sp.solve(poly.as_expr(), m):
            val = sp.N(r, _PREC)
            if abs(sp.im(val)) < sp.Float(10) ** (-30):
                roots.append(_simp(sp.re(r)) if not r.is_real else _simp(r))
    return roots


def _sorted_unique(values: Sequence[sp.Expr]) -> list[sp.Expr]:
    out: list[sp.Expr] = []
    for v in sorted(values, key=lambda e: _hp(e)):
        if out and abs(_hp(v) - _hp(out[-1])) < sp.Float(10) ** (-30) * (1 + abs(_hp(v))):
            continue
        out.append(v)
    return out


def _sample_inside(lo: sp.Expr, hi: sp.Expr) -> sp.Rational:
    """开区间 (lo, hi) 内的一个有理采样点（lo/hi 可为 ±∞）。"""
    if lo == -sp.oo and hi == sp.oo:
        return sp.Integer(0)
    if lo == -sp.oo:
        return sp.Integer(math.floor(_f(hi)) - 1)
    if hi == sp.oo:
        return sp.Integer(math.ceil(_f(lo)) + 1)
    mid = (_hp(lo) + _hp(hi)) / 2
    return sp.Rational(str(mid))


def _same(u: sp.Expr, v: sp.Expr) -> bool:
    if u in (sp.oo, -sp.oo) or v in (sp.oo, -sp.oo):
        return u == v
    return abs(_hp(u) - _hp(v)) < sp.Float(10) ** (-25) * (1 + abs(_hp(u)))


def _less(u: sp.Expr, v: sp.Expr) -> bool:
    if u == v:
        return False
    if u == -sp.oo or v == sp.oo:
        return True
    if u == sp.oo or v == -sp.oo:
        return False
    return (not _same(u, v)) and _hp(u) < _hp(v)


def _one_sided_limit(g: sp.Expr, den: sp.Expr, at: sp.Expr, side: str) -> sp.Expr:
    """有理式 g 在有限点 at 的单侧极限（避免对 CRootOf 调用 sp.limit）。"""
    d_at = _hp(den.subs(m, at))
    if abs(d_at) > sp.Float(10) ** (-30):
        return _simp(g.subs(m, at))
    eps = sp.Float(10) ** (-12) * (1 + abs(_hp(at)))
    probe = _hp(at) + (eps if side == "+" else -eps)
    val = sp.N(g.subs(m, probe), _PREC)
    return sp.oo if val > 0 else -sp.oo


def _at(kind: str, mval: sp.Expr | None, attained: bool) -> dict[str, Any]:
    return {"kind": kind, "m": None if mval is None else _latex(mval), "attained": attained}


def _merge_pieces(pieces: list[RangePiece]) -> list[RangePiece]:
    pieces = sorted(pieces, key=lambda p: (-1e300 if p.lo == -sp.oo else float(_hp(p.lo))))
    out: list[RangePiece] = []
    for p in pieces:
        if not out:
            out.append(p.model_copy())
            continue
        cur = out[-1]
        touching = _same(p.lo, cur.hi) and (cur.hi_closed or p.lo_closed)
        if _less(p.lo, cur.hi) or touching:
            if _same(p.lo, cur.lo) and p.lo_closed and not cur.lo_closed:
                cur.lo_closed, cur.lo_at = True, p.lo_at
            if _less(cur.hi, p.hi):
                cur.hi, cur.hi_closed, cur.hi_at = p.hi, p.hi_closed, p.hi_at
            elif _same(cur.hi, p.hi) and p.hi_closed and not cur.hi_closed:
                cur.hi_closed, cur.hi_at = True, p.hi_at
        else:
            out.append(p.model_copy())
    return out


# ──────────────────────────────────────────────────────────────────────────────
# 原语
# ──────────────────────────────────────────────────────────────────────────────


def parse_exact_number(value: NumberLiteral, *, positive: bool = False, bound: int = MAX_COORDINATE) -> sp.Expr:
    """受限字面量解析：整数 / 有限小数 / ``p/q`` / ``k*sqrt(m)`` / ``k√m/q``（可带符号）。

    ``positive=True`` 时要求结果 > 0；结果绝对值不超过 ``bound``。任何其它写法一律拒绝，
    绝不对字符串调用 ``sympify``。
    """
    return _parse_literal(value, positive=positive, bound=bound)


def build_conic(spec: ConicSpec) -> ConicData:
    """按标准位置构造圆锥曲线：隐式方程、标准方程 LaTeX、焦点、顶点、离心率、准线。"""
    if spec.kind in ("ellipse", "hyperbola"):
        if spec.a is None or spec.b is None or spec.p is not None:
            raise ValueError(f"{spec.kind} needs a and b (and no p)")
        a = _parse_literal(spec.a, positive=True, bound=MAX_PARAMETER)
        b = _parse_literal(spec.b, positive=True, bound=MAX_PARAMETER)
        if spec.kind == "ellipse":
            if not (a > b):
                raise ValueError("ellipse with foci on the x-axis needs a > b (a == b is a circle)")
            c = _simp(sp.sqrt(a**2 - b**2))
            implicit = x**2 / a**2 + y**2 / b**2 - 1
            eq_latex = f"{_term('x^2', a**2)}+{_term('y^2', b**2)}=1"
            vertices = {"A1": (-a, sp.Integer(0)), "A2": (a, sp.Integer(0)), "B1": (sp.Integer(0), -b), "B2": (sp.Integer(0), b)}
            asym: list[Any] = []
            board = {"kind": "ellipse", "a": _f(a), "b": _f(b), "center": [0.0, 0.0]}
        else:
            c = _simp(sp.sqrt(a**2 + b**2))
            implicit = x**2 / a**2 - y**2 / b**2 - 1
            eq_latex = f"{_term('x^2', a**2)}-{_term('y^2', b**2)}=1"
            vertices = {"A1": (-a, sp.Integer(0)), "A2": (a, sp.Integer(0))}
            asym = [_simp(b / a), _simp(-b / a)]
            board = {"kind": "hyperbola", "a": _f(a), "b": _f(b), "center": [0.0, 0.0], "orient": "x", "asymptotes": True}
        return ConicData(
            kind=spec.kind, a=a, b=b, c=c, implicit=implicit, eq_latex=eq_latex,
            foci={"F1": (-c, sp.Integer(0)), "F2": (c, sp.Integer(0))},
            vertices=vertices, eccentricity=_simp(c / a),
            directrices=[_simp(-a**2 / c), _simp(a**2 / c)],
            asymptote_slopes=asym, board=board,
        )
    if spec.p is None or spec.a is not None or spec.b is not None:
        raise ValueError("parabola needs p (and no a/b)")
    p = _parse_literal(spec.p, positive=True, bound=MAX_PARAMETER)
    return ConicData(
        kind="parabola", p=p, implicit=y**2 - 2 * p * x,
        eq_latex=r"y^2=%sx" % ("" if _simp(2 * p) == 1 else sp.latex(_simp(2 * p))),
        foci={"F": (_simp(p / 2), sp.Integer(0))},
        vertices={"O": (sp.Integer(0), sp.Integer(0))},
        eccentricity=sp.Integer(1), directrices=[_simp(-p / 2)],
        board={"kind": "parabola", "p": _f(p), "center": [0.0, 0.0], "axis": "x"},
    )


def chord_vieta(conic: ConicData, *, through: tuple[sp.Expr, sp.Expr]) -> ChordVieta:
    """直线 ``x = m·y + c`` 过点 ``through``，与曲线联立 → 关于 y 的二次方程与韦达量。"""
    x0, y0 = sp.nsimplify(through[0]), sp.nsimplify(through[1])
    c = x0 - m * y0
    numer = sp.numer(sp.together(sp.expand(conic.implicit.subs(x, m * y + c))))
    poly = sp.Poly(sp.expand(numer), y)
    if poly.degree() != 2:
        raise ValueError(f"substitution did not give a quadratic in y: {poly}")
    qa, qb, qc = (sp.expand(k) for k in poly.all_coeffs())
    if sp.Poly(qa, m).is_zero:
        raise ValueError("degenerate quadratic coefficient")
    y_sum = sp.cancel(-qb / qa)
    y_prod = sp.cancel(qc / qa)
    return ChordVieta(
        through=(x0, y0), c=c, qa=qa, qb=qb, qc=qc,
        y_sum=y_sum, y_prod=y_prod,
        x_sum=sp.cancel(m * y_sum + 2 * c),
        x_prod=sp.cancel(m**2 * y_prod + m * c * y_sum + c**2),
        disc=sp.factor(sp.expand(qb**2 - 4 * qa * qc)),
    )


def horizontal_line_meets_twice(conic: ConicData, *, through: tuple[sp.Expr, sp.Expr]) -> bool:
    """过定点的水平线 ``y = y0``（对应 ``m → ∞``）是否与曲线交于两个不同点（即为合法弦）。

    抛物线 ``y² = 2px`` 的水平线与对称轴平行，只交一点 → ``False``。
    """
    y0 = sp.nsimplify(through[1])
    expr = sp.expand(conic.implicit.subs(y, y0))
    poly = sp.Poly(sp.numer(sp.together(expr)), x)
    if poly.degree() != 2:
        return False
    a2, a1, a0 = poly.all_coeffs()
    return bool(_simp(a1**2 - 4 * a2 * a0) > 0)


def line_param_through(through: tuple[sp.Expr, sp.Expr], *, point: tuple[sp.Expr, sp.Expr]) -> sp.Expr | None:
    """过 ``through`` 且经过 ``point`` 的直线对应的 m；水平线返回 ``None``。两点重合抛错。"""
    x0, y0 = sp.nsimplify(through[0]), sp.nsimplify(through[1])
    px, py = sp.nsimplify(point[0]), sp.nsimplify(point[1])
    if _simp(px - x0) == 0 and _simp(py - y0) == 0:
        raise ValueError("point coincides with the through-point")
    if _simp(py - y0) == 0:
        return None
    return _simp((px - x0) / (py - y0))


def dot_product_expr(chord: ChordVieta, *, vertex: tuple[sp.Expr, sp.Expr]) -> sp.Expr:
    """以 M=vertex 为起点、A、B 为交点的数量积 ``MA·MB`` 关于 m 的有理式。

    ``(x1−Mx)(x2−Mx)+(y1−My)(y2−My) = x1x2 − Mx(x1+x2) + Mx² + y1y2 − My(y1+y2) + My²``
    """
    mx, my = sp.nsimplify(vertex[0]), sp.nsimplify(vertex[1])
    expr = chord.x_prod - mx * chord.x_sum + mx**2 + chord.y_prod - my * chord.y_sum + my**2
    return sp.cancel(sp.together(expr))


def chord_length_sq_expr(chord: ChordVieta) -> sp.Expr:
    """弦长平方 ``|AB|² = (1+m²)[(y1+y2)² − 4y1y2]`` 关于 m 的有理式。"""
    return sp.factor(sp.cancel((1 + m**2) * (chord.y_sum**2 - 4 * chord.y_prod)))


def triangle_area_sq_expr(chord: ChordVieta, *, vertex: tuple[sp.Expr, sp.Expr]) -> sp.Expr:
    """``S△(vertex,A,B)²`` 关于 m 的有理式。

    ``S = ½·|AB|·d``，``d = |vx − m·vy − c| / √(1+m²)``，故
    ``S² = ¼·[(y1+y2)² − 4y1y2]·(vx − m·vy − c)²``（``1+m²`` 约去）。
    """
    vx, vy = sp.nsimplify(vertex[0]), sp.nsimplify(vertex[1])
    lin = vx - m * vy - chord.c
    return sp.factor(sp.cancel(sp.Rational(1, 4) * (chord.y_sum**2 - 4 * chord.y_prod) * lin**2))


def constant_in_m(expr: sp.Expr) -> tuple[bool, sp.Expr]:
    """判断 expr 是否与 m 无关（定值），返回 (是否定值, m=0 处的值)。"""
    e = sp.cancel(sp.together(expr))
    return bool(sp.simplify(sp.diff(e, m)) == 0), _simp(e.subs(m, 0))


def range_over_m(
    expr: sp.Expr,
    *,
    chord: ChordVieta,
    horizontal_valid: bool,
    excluded_m: Sequence[sp.Expr] = (),
) -> ValueRange:
    """目标量 ``expr(m)``（有理式）在"合法直线"集合上的精确取值范围，含开闭端点判定。

    合法直线：二次项系数 ``qa(m) ≠ 0``、判别式 ``Δ(m) > 0``、``m`` 不在 ``excluded_m`` 中；
    此外水平线（``m → ∞``）当且仅当 ``horizontal_valid`` 时合法。

    在每个合法开区间上收集：区间内驻点（取到）、区间端点单侧极限（有限端点取不到；
    ``±∞`` 端点仅当水平线合法时取到）。每段像为一区间，最后求并（相接且一侧闭则合并）。
    """
    g = sp.cancel(sp.together(expr))
    if g.free_symbols - {m}:
        raise ValueError("target must depend on m only")
    _num, den = sp.fraction(g)

    breaks = _real_roots(chord.qa) + _real_roots(chord.disc) + _real_roots(den)
    breaks += [sp.nsimplify(e) for e in excluded_m]
    breaks = _sorted_unique(breaks)
    edges: list[sp.Expr] = [-sp.oo, *breaks, sp.oo]

    valid: list[tuple[sp.Expr, sp.Expr]] = []
    for lo, hi in itertools.pairwise(edges):
        s = _sample_inside(lo, hi)
        if abs(_hp(chord.qa.subs(m, s))) > sp.Float(10) ** (-30) and _hp(chord.disc.subs(m, s)) > 0:
            valid.append((lo, hi))
    if not valid:
        raise ValueError("no line through the given point cuts a chord")

    # 合法 m 集合的 LaTeX（相邻开区间之间的断点即被排除的 m）
    valid_m_latex = (
        r"m\in\mathbb{R}"
        if len(valid) == 1 and valid[0] == (-sp.oo, sp.oo)
        else r"m\in " + _interval_latex([(lo, hi, False, False) for lo, hi in valid])
    )

    is_const = bool(sp.simplify(sp.diff(g, m)) == 0)
    if is_const:
        val = _simp(g.subs(m, _sample_inside(*valid[0])))
        at = _at("constant", None, True)
        piece = RangePiece(lo=val, hi=val, lo_closed=True, hi_closed=True, lo_at=at, hi_at=at)
        return ValueRange(pieces=[piece], constant=val, latex=_latex(val), valid_m_latex=valid_m_latex)

    crit = _real_roots(sp.numer(sp.together(sp.diff(g, m))))
    lim_inf = {sp.oo: sp.limit(g, m, sp.oo), -sp.oo: sp.limit(g, m, -sp.oo)}

    pieces: list[RangePiece] = []
    for lo, hi in valid:
        cands: list[tuple[sp.Expr, dict[str, Any]]] = []
        for r in crit:
            if _less(lo, r) and _less(r, hi):
                kind = "vertical" if _same(r, 0) else "critical"
                cands.append((_simp(g.subs(m, r)), _at(kind, r, True)))
        if lo == -sp.oo:
            cands.append((_simp(lim_inf[-sp.oo]), _at("horizontal", None, horizontal_valid)))
        else:
            cands.append((_one_sided_limit(g, den, lo, "+"), _at("boundary", lo, False)))
        if hi == sp.oo:
            cands.append((_simp(lim_inf[sp.oo]), _at("horizontal", None, horizontal_valid)))
        else:
            cands.append((_one_sided_limit(g, den, hi, "-"), _at("boundary", hi, False)))
        lo_v = min((v for v, _ in cands), key=lambda v: -1e300 if v == -sp.oo else (1e300 if v == sp.oo else float(_hp(v))))
        hi_v = max((v for v, _ in cands), key=lambda v: -1e300 if v == -sp.oo else (1e300 if v == sp.oo else float(_hp(v))))
        lo_hits = [a for v, a in cands if _same(v, lo_v)]
        hi_hits = [a for v, a in cands if _same(v, hi_v)]
        lo_att = [a for a in lo_hits if a["attained"]]
        hi_att = [a for a in hi_hits if a["attained"]]
        pieces.append(RangePiece(
            lo=lo_v, hi=hi_v,
            lo_closed=lo_v != -sp.oo and bool(lo_att),
            hi_closed=hi_v != sp.oo and bool(hi_att),
            lo_at=(lo_att or lo_hits)[0] if lo_v != -sp.oo else _at("unbounded", None, False),
            hi_at=(hi_att or hi_hits)[0] if hi_v != sp.oo else _at("unbounded", None, False),
        ))

    merged = _merge_pieces(pieces)
    latex = _interval_latex([(p.lo, p.hi, p.lo_closed, p.hi_closed) for p in merged])
    return ValueRange(pieces=merged, latex=latex, valid_m_latex=valid_m_latex)


def sqrt_range(value_range: ValueRange) -> ValueRange:
    """把非负量平方的取值范围映射为其算术平方根的取值范围（√ 单调，开闭不变）。"""
    pieces = []
    for p in value_range.pieces:
        if _less(p.lo, 0):
            raise ValueError("sqrt_range needs a non-negative range")
        lo = p.lo if p.lo == sp.oo else _simp(sp.sqrt(p.lo))
        hi = p.hi if p.hi == sp.oo else _simp(sp.sqrt(p.hi))
        pieces.append(p.model_copy(update={"lo": lo, "hi": hi}))
    const = None if value_range.constant is None else _simp(sp.sqrt(value_range.constant))
    latex = _latex(const) if const is not None else _interval_latex([(p.lo, p.hi, p.lo_closed, p.hi_closed) for p in pieces])
    return ValueRange(pieces=pieces, constant=const, latex=latex, valid_m_latex=value_range.valid_m_latex)


def interval_latex(pieces: Sequence[tuple[sp.Expr, sp.Expr, bool, bool]]) -> str:
    """区间（并）LaTeX：``[(lo, hi, lo_closed, hi_closed), ...]`` → ``\\left[-3,\\ \\frac{7}{4}\\right]``。"""
    return _interval_latex(pieces)


def conic_latex_expr(expr: sp.Expr) -> str:
    """化简后的 LaTeX（±∞ 写作 ``\\pm\\infty``）。"""
    return _latex(expr)


def numeric_range_check(
    kind: str,
    *,
    a: float = 0.0,
    b: float = 0.0,
    p: float = 0.0,
    through: tuple[float, float],
    target: str,
    vertex: tuple[float, float] | None = None,
    samples: int = 36000,
) -> NumericRangeCheck:
    """独立浮点复核：只用 ``math``，不走 sympy，不用韦达公式。

    以倾斜角 θ 均匀密集采样过定点的直线（等价于 ``m = cot θ``：θ=90° 即 ``m=0``，
    θ→0° 即 ``|m|→∞``，水平线 θ=0 本身也被采样），直接用浮点解直线参数式与曲线的
    二次方程得交点 A、B 再算目标量。合法采样按角度连续分段，每段：
    - 段内局部极值用黄金分割细化（逼近驻点处取到的端点）；
    - 段两端用二分逼近失效边界（切线 / 渐近线方向 / 退化三角形），逼近取不到的端点；
      交点距离超过 ``1e6·尺度`` 即视为"趋于无穷"的边界（浮点精度所限），故无界端点
      表现为采样值量级 ≳ 1e5·尺度。
    各段 [min, max] 求并即为数值取值范围估计。
    """
    if kind == "ellipse":
        ca, cc, cd, cf = 1 / a**2, 1 / b**2, 0.0, -1.0
    elif kind == "hyperbola":
        ca, cc, cd, cf = 1 / a**2, -1 / b**2, 0.0, -1.0
    elif kind == "parabola":
        ca, cc, cd, cf = 0.0, 1.0, -2 * p, 0.0
    else:
        raise ValueError(f"unsupported conic kind: {kind}")
    x0, y0 = float(through[0]), float(through[1])
    vx, vy = (float(vertex[0]), float(vertex[1])) if vertex is not None else (0.0, 0.0)
    if target in TARGETS_NEEDING_VERTEX and vertex is None:
        raise ValueError(f"{target} needs a vertex")
    size = max(1.0, abs(a), abs(b), abs(p), abs(x0), abs(y0), abs(vx), abs(vy))

    def value(theta: float) -> float | None:
        dx, dy = math.cos(theta), math.sin(theta)
        qa = ca * dx * dx + cc * dy * dy
        qb = 2 * ca * x0 * dx + 2 * cc * y0 * dy + cd * dx
        qc = ca * x0 * x0 + cc * y0 * y0 + cd * x0 + cf
        if abs(qa) <= 1e-12 * (abs(ca) + abs(cc)):
            return None
        disc = qb * qb - 4 * qa * qc
        if disc <= 1e-12 * (qb * qb + abs(4 * qa * qc)) or disc <= 0:
            return None
        sd = math.sqrt(disc)
        q = -(qb + math.copysign(sd, qb)) / 2  # 数值稳定求根，避免大根时小根相消
        t1, t2 = q / qa, qc / q
        if max(abs(t1), abs(t2)) > 1e6 * size:  # 交点已"远至无穷"：视为渐近 / 平行方向的边界
            return None
        ax, ay, bx, by = x0 + t1 * dx, y0 + t1 * dy, x0 + t2 * dx, y0 + t2 * dy
        if target in ("dot_product", "fixed_value_dot"):
            return (ax - vx) * (bx - vx) + (ay - vy) * (by - vy)
        if target == "chord_length":
            return math.hypot(ax - bx, ay - by)
        if target == "triangle_area":
            s = abs((ax - vx) * (by - vy) - (bx - vx) * (ay - vy)) / 2
            return None if s <= 1e-12 * size * size else s
        raise ValueError(f"unsupported target: {target}")

    n = max(360, int(samples))
    n += n % 2  # 保证 θ=90°（m=0）在网格上
    step = math.pi / n
    thetas = [k * step for k in range(n)]
    vals = [value(t) for t in thetas]
    n_valid = sum(v is not None for v in vals)
    if n_valid == 0:
        raise ValueError("no sampled line cuts a chord")

    def refine_edge(t_ok: float, t_bad: float) -> float:
        best = value(t_ok)
        for _ in range(60):
            mid = (t_ok + t_bad) / 2
            v = value(mid)
            if v is None:
                t_bad = mid
            else:
                t_ok, best = mid, v
        return float(best)  # type: ignore[arg-type]

    def golden(t_lo: float, t_hi: float, sign: float) -> float | None:
        """黄金分割细化局部极值；失效点（None）按"最差"处理，返回过程中见到的最优合法值。"""
        gr = (math.sqrt(5) - 1) / 2
        best: float | None = None

        def ev(t: float) -> float:
            nonlocal best
            v = value(t)
            if v is None:
                return -math.inf
            if best is None or sign * v > sign * best:
                best = v
            return sign * v

        c1, c2 = t_hi - gr * (t_hi - t_lo), t_lo + gr * (t_hi - t_lo)
        f1, f2 = ev(c1), ev(c2)
        for _ in range(80):
            if f1 > f2:
                t_hi, c2, f2 = c2, c1, f1
                c1 = t_hi - gr * (t_hi - t_lo)
                f1 = ev(c1)
            else:
                t_lo, c1, f1 = c1, c2, f2
                c2 = t_lo + gr * (t_hi - t_lo)
                f2 = ev(c2)
        return best

    # 按角度（循环：θ=π 与 θ=0 是同一条直线）切分连续合法段
    if n_valid == n:
        runs = [list(range(n))]
        circular = True
    else:
        circular = False
        start = next(k for k in range(n) if vals[k] is None)
        runs, cur = [], []
        for j in range(1, n + 1):
            k = (start + j) % n
            if vals[k] is None:
                if cur:
                    runs.append(cur)
                cur = []
            else:
                cur.append(k)
        if cur:
            runs.append(cur)

    def theta_of(k_from: int, k_to: int) -> tuple[float, float]:
        """相邻索引的角度（处理 n−1 → 0 的回绕）。"""
        t1, t2 = thetas[k_from], thetas[k_to]
        if k_from == n - 1 and k_to == 0:
            t2 = math.pi
        if k_from == 0 and k_to == n - 1:
            t2 = -step
        return t1, t2

    pieces: list[tuple[float, float]] = []
    for run in runs:
        rv = [vals[k] for k in run]
        lo_v, hi_v = min(rv), max(rv)  # type: ignore[type-var]
        if not circular:
            for end, nb in ((run[0], (run[0] - 1) % n), (run[-1], (run[-1] + 1) % n)):
                t_ok, t_bad = theta_of(end, nb)
                e = refine_edge(t_ok, t_bad)
                lo_v, hi_v = min(lo_v, e), max(hi_v, e)
        if hi_v - lo_v > 1e-12 * (1 + abs(hi_v)):
            refined = 0
            idx = range(len(run)) if circular else range(1, len(run) - 1)
            for i in idx:
                if refined >= 64:
                    break
                kp, k, kn = run[i - 1], run[i], run[(i + 1) % len(run)]
                vp, v, vn = vals[kp], vals[k], vals[kn]
                for sign in (1.0, -1.0):
                    if sign * v > sign * vp and sign * v >= sign * vn:  # type: ignore[operator]
                        t_c = thetas[k]
                        g = golden(t_c - step, t_c + step, sign)
                        refined += 1
                        if g is not None:
                            lo_v, hi_v = min(lo_v, g), max(hi_v, g)
        pieces.append((float(lo_v), float(hi_v)))

    pieces.sort()
    merged: list[list[float]] = []
    for lo_v, hi_v in pieces:
        if merged and lo_v <= merged[-1][1] + 1e-6 * (1 + abs(merged[-1][1])):
            merged[-1][1] = max(merged[-1][1], hi_v)
        else:
            merged.append([lo_v, hi_v])
    return NumericRangeCheck(
        pieces=[(lo_v, hi_v) for lo_v, hi_v in merged],
        n_samples=n,
        n_valid=n_valid,
        sampled_min=merged[0][0],
        sampled_max=merged[-1][1],
    )
