"""
立体几何确定性计算原语（oprim 层）
=====================================

坐标、向量与最终答案全部由 sympy 精确符号运算得出，根式自动化简，
不依赖 LLM、不做心算。同一套坐标同时喂给解题步骤与 3D 渲染，保证
"图、解、答"同源一致。

3O 范式 oprim 约束：
- 每个公开函数是一次原子计算，公开函数之间互不调用（只共享 ``_`` 私有工具）
- 纯函数：无 IO、无全局状态、无随机；纯计算故为同步函数
- 签名：≤1 个核心位置参数，其余 keyword-only
- 输入输出类型显式（Pydantic 模型 / sympy 对象）

安全：尺寸只接受受限字面量（整数、分数、``k*sqrt(m)`` 形式），
绝不对外部字符串调用 ``sympy.sympify``（其内部走 ``eval``）。

坐标约定：数学坐标 z 轴向上；three.js 渲染坐标 y 轴向上，
``three = (x, z, y) * scale``。

来源：几何内核与几何体拓扑派生自 wy51ai/edulab
``skills/edu-solid-geometry/lib/{geometry_kernel,bodies}.py``
（commit 6a9c8766061ca7101d10bab6fe3af716ec47bb07，Apache-2.0，
Copyright 2026 WY (@akokoi1)）。已改写为 3O oprim 形态并新增
受限尺寸解析、派生点、独立浮点复核。
"""

from __future__ import annotations

import math
import re
from typing import Literal

import sympy as sp
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ──────────────────────────────────────────────────────────────────────────────
# 类型
# ──────────────────────────────────────────────────────────────────────────────

BodyType = Literal["cube", "cuboid", "regular_quad_pyramid", "regular_tetrahedron"]
QueryType = Literal[
    "line_plane_angle",
    "line_line_angle",
    "point_plane_distance",
    "dihedral_angle",
    "tetra_volume",
    "segment_length",
]

POINT_NAME_RE = re.compile(r"^[A-Z][0-9]?$")
MAX_DIMENSION = 1000

BODY_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "cube": ("edge",),
    "cuboid": ("length", "width", "height"),
    "regular_quad_pyramid": ("base_edge", "height"),
    "regular_tetrahedron": ("edge",),
}

QUERY_ARITY: dict[str, dict[str, int]] = {
    "line_plane_angle": {"line": 2, "plane": 3},
    "line_line_angle": {"line": 2, "line2": 2},
    "point_plane_distance": {"point": 1, "plane": 3},
    "dihedral_angle": {"edge": 2, "faces": 2},
    "tetra_volume": {"points": 4},
    "segment_length": {"points": 2},
}


def _check_name(name: str) -> str:
    if not POINT_NAME_RE.match(name):
        raise ValueError(f"invalid point name: {name!r}")
    return name


class GivenPoint(BaseModel):
    """额外构造点。

    - ``midpoint``: ``of=[X, Y]``，取中点
    - ``on_segment``: ``of=[X, Y]``，``ratio="p/q"``，点 = X + ratio·(Y − X)
    - ``centroid``: ``of=[...]``（2–4 个点），取重心
    """

    name: str
    kind: Literal["midpoint", "on_segment", "centroid"]
    of: list[str] = Field(min_length=2, max_length=4)
    ratio: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def _name_ok(cls, v: str) -> str:
        return _check_name(v)

    @field_validator("of")
    @classmethod
    def _of_ok(cls, v: list[str]) -> list[str]:
        return [_check_name(x) for x in v]


class SolidQuery(BaseModel):
    """所求。字段按 ``type`` 取用，元数见 ``QUERY_ARITY``。"""

    type: QueryType
    line: list[str] | None = None
    line2: list[str] | None = None
    plane: list[str] | None = None
    point: list[str] | None = None
    edge: list[str] | None = None
    faces: list[str] | None = None
    points: list[str] | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("line", "line2", "plane", "point", "edge", "faces", "points")
    @classmethod
    def _names_ok(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else [_check_name(x) for x in v]

    def operand(self, key: str) -> list[str]:
        value = getattr(self, key)
        need = QUERY_ARITY[self.type][key]
        if value is None or len(value) != need:
            raise ValueError(f"{self.type}.{key} needs {need} point name(s)")
        return list(value)


class SolidGeometrySpec(BaseModel):
    """结构化题目（文字 / 图片 / 随机三入口归一后的中间产物）。"""

    body: BodyType
    dims: dict[str, int | float | str]
    givens: list[GivenPoint] = Field(default_factory=list, max_length=6)
    query: SolidQuery
    language: Literal["zh-CN"] = "zh-CN"

    model_config = ConfigDict(extra="forbid")


# ──────────────────────────────────────────────────────────────────────────────
# 私有工具（可被多个公开原语共享；公开原语之间不互相调用）
# ──────────────────────────────────────────────────────────────────────────────

_INT_RE = re.compile(r"^\s*(\d{1,4})(?:\s*/\s*(\d{1,4}))?\s*$")
_SQRT_RE = re.compile(
    r"^\s*(\d{1,4})?\s*\*?\s*(?:sqrt|√)\s*\(?\s*(\d{1,4})\s*\)?\s*(?:/\s*(\d{1,4}))?\s*$"
)


def _v(*comps: sp.Expr | int) -> sp.Matrix:
    return sp.Matrix([sp.nsimplify(c) for c in comps])


def _simp(expr: sp.Expr) -> sp.Expr:
    return sp.radsimp(sp.simplify(expr))


def _norm(v: sp.Matrix) -> sp.Expr:
    return sp.sqrt(sum(c**2 for c in v))


# ──────────────────────────────────────────────────────────────────────────────
# 原语
# ──────────────────────────────────────────────────────────────────────────────


def parse_dimension(value: int | float | str) -> sp.Expr:
    """受限尺寸解析：整数 / 有限小数 / ``p/q`` / ``k*sqrt(m)`` / ``k√m/q``。

    结果必须为正且不超过 ``MAX_DIMENSION``。任何其它写法一律拒绝。
    """
    if isinstance(value, bool):
        raise ValueError("dimension must be numeric")
    if isinstance(value, int):
        expr: sp.Expr = sp.Integer(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("dimension must be finite")
        expr = sp.Rational(repr(value))
    elif isinstance(value, str):
        m = _INT_RE.match(value)
        if m:
            num, den = int(m.group(1)), int(m.group(2) or 1)
            if den == 0:
                raise ValueError("zero denominator")
            expr = sp.Rational(num, den)
        else:
            m = _SQRT_RE.match(value)
            if not m:
                raise ValueError(f"unsupported dimension literal: {value!r}")
            coef = int(m.group(1) or 1)
            radicand = int(m.group(2))
            den = int(m.group(3) or 1)
            if den == 0:
                raise ValueError("zero denominator")
            expr = sp.Rational(coef, den) * sp.sqrt(radicand)
    else:
        raise ValueError("dimension must be int, float or str")
    if not (expr > 0) or expr > MAX_DIMENSION:
        raise ValueError(f"dimension out of range (0, {MAX_DIMENSION}]")
    return sp.nsimplify(expr)


def build_body_points(body: str, *, dims: dict[str, sp.Expr]) -> dict[str, sp.Matrix]:
    """按标准建系约定给出几何体全部顶点的精确数学坐标。"""
    if body in ("cube", "cuboid"):
        if body == "cube":
            lx = ly = lz = dims["edge"]
        else:
            lx, ly, lz = dims["length"], dims["width"], dims["height"]
        return {
            "A": _v(0, 0, 0), "B": _v(lx, 0, 0), "C": _v(lx, ly, 0), "D": _v(0, ly, 0),
            "A1": _v(0, 0, lz), "B1": _v(lx, 0, lz), "C1": _v(lx, ly, lz), "D1": _v(0, ly, lz),
        }
    if body == "regular_quad_pyramid":
        a, h = dims["base_edge"], dims["height"]
        d = _simp(a / sp.sqrt(2))  # 半对角线
        return {
            "O": _v(0, 0, 0), "A": _v(d, 0, 0), "B": _v(0, d, 0),
            "C": _v(-d, 0, 0), "D": _v(0, -d, 0), "P": _v(0, 0, h),
        }
    if body == "regular_tetrahedron":
        k = _simp(dims["edge"] / (2 * sp.sqrt(2)))
        base = {"A": (1, 1, 1), "B": (1, -1, -1), "C": (-1, 1, -1), "D": (-1, -1, 1)}
        return {n: sp.Matrix([_simp(k * c) for c in xyz]) for n, xyz in base.items()}
    raise ValueError(f"unsupported body: {body}")


def body_topology(body: str) -> dict[str, list]:
    """几何体的顶点小球与骨架棱（看不见的棱为虚线）。"""

    def e(a: str, b: str, dashed: bool = False) -> dict:
        return {"a": a, "b": b, "dashed": True} if dashed else {"a": a, "b": b}

    if body in ("cube", "cuboid"):
        return {
            "spheres": ["A", "B", "C", "D", "A1", "B1", "C1", "D1"],
            "edges": [
                e("A", "B"), e("B", "C"), e("C", "D", True), e("D", "A", True),
                e("A1", "B1"), e("B1", "C1"), e("C1", "D1"), e("D1", "A1"),
                e("A", "A1"), e("B", "B1"), e("C", "C1"), e("D", "D1", True),
            ],
        }
    if body == "regular_quad_pyramid":
        return {
            "spheres": ["P", "A", "B", "C", "D", "O"],
            "edges": [
                e("A", "B"), e("B", "C"), e("C", "D", True), e("D", "A", True),
                e("P", "A"), e("P", "B"), e("P", "C"), e("P", "D", True),
                e("P", "O", True),
            ],
        }
    if body == "regular_tetrahedron":
        return {
            "spheres": ["A", "B", "C", "D"],
            "edges": [e("A", "B"), e("B", "C"), e("C", "A"), e("D", "A"), e("D", "B"), e("D", "C", True)],
        }
    raise ValueError(f"unsupported body: {body}")


def derive_given_points(
    points: dict[str, sp.Matrix], *, givens: list[GivenPoint]
) -> dict[str, sp.Matrix]:
    """按顺序构造派生点，返回新的点表（不修改入参）。"""
    out = dict(points)
    for g in givens:
        if g.name in out:
            raise ValueError(f"point {g.name} already defined")
        missing = [n for n in g.of if n not in out]
        if missing:
            raise ValueError(f"{g.name}: unknown point(s) {missing}")
        src = [out[n] for n in g.of]
        if g.kind == "midpoint":
            if len(src) != 2:
                raise ValueError("midpoint needs exactly 2 points")
            p = (src[0] + src[1]) / 2
        elif g.kind == "on_segment":
            if len(src) != 2 or g.ratio is None:
                raise ValueError("on_segment needs 2 points and a ratio")
            m = _INT_RE.match(g.ratio)
            if not m:
                raise ValueError(f"ratio must be p/q, got {g.ratio!r}")
            t = sp.Rational(int(m.group(1)), int(m.group(2) or 1))
            if not (0 <= t <= 1):
                raise ValueError("ratio must lie in [0, 1]")
            p = src[0] + t * (src[1] - src[0])
        else:
            p = sum(src, sp.zeros(3, 1)) / len(src)
        out[g.name] = sp.Matrix([_simp(c) for c in p])
    return out


def plane_normal(plane: tuple[sp.Matrix, sp.Matrix, sp.Matrix]) -> tuple[sp.Matrix, sp.Matrix]:
    """三点确定平面的法向量：返回 (叉积原值, 约简后的最简方向)。"""
    p, q, r = plane
    raw = (q - p).cross(r - p)
    raw = sp.Matrix([_simp(c) for c in raw])
    if all(c == 0 for c in raw):
        raise ValueError("the three points are collinear")
    nonzero = [c for c in raw if c != 0]
    g = nonzero[0]
    for c in nonzero[1:]:
        g = sp.gcd(g, c)
    reduced = sp.Matrix([_simp(c / g) for c in raw]) if g != 0 else raw
    if not all(c.is_rational for c in reduced):
        reduced = raw
    # 让第一个非零分量为正，便于展示
    first = next(c for c in reduced if c != 0)
    if first < 0:
        reduced = -reduced
    return raw, reduced


def line_plane_angle_sin(direction: sp.Matrix, *, normal: sp.Matrix) -> sp.Expr:
    """线面角正弦 sinθ = |v·n| / (|v||n|)。"""
    if all(c == 0 for c in direction):
        raise ValueError("degenerate line")
    return _simp(sp.Abs(direction.dot(normal)) / (_norm(direction) * _norm(normal)))


def line_line_angle_cos(direction: sp.Matrix, *, other: sp.Matrix) -> sp.Expr:
    """两直线夹角余弦 cosθ = |d1·d2| / (|d1||d2|)（取锐角）。"""
    d1, d2 = direction, other
    if all(c == 0 for c in d1) or all(c == 0 for c in d2):
        raise ValueError("degenerate line")
    return _simp(sp.Abs(d1.dot(d2)) / (_norm(d1) * _norm(d2)))


def point_plane_distance(point: sp.Matrix, *, plane_point: sp.Matrix, normal: sp.Matrix) -> sp.Expr:
    """点到平面距离 |(P − P0)·n| / |n|。"""
    return _simp(sp.Abs((point - plane_point).dot(normal)) / _norm(normal))


def dihedral_angle_cos(
    edge: tuple[sp.Matrix, sp.Matrix], *, faces: tuple[sp.Matrix, sp.Matrix]
) -> sp.Expr:
    """二面角 C-AB-D 的带符号余弦（正=锐角，负=钝角）。

    ``edge=(A, B)`` 为棱，``faces=(C, D)`` 分别位于两个半平面内；
    在两个半平面内各取垂直于棱 AB 的向量再求夹角。
    """
    a, b = edge
    c, d = faces
    u = b - a
    if all(x == 0 for x in u):
        raise ValueError("degenerate edge")

    def perp(p: sp.Matrix) -> sp.Matrix:
        w = p - a
        return w - (w.dot(u) / u.dot(u)) * u

    v1, v2 = perp(c), perp(d)
    if all(x == 0 for x in v1) or all(x == 0 for x in v2):
        raise ValueError("face point lies on the edge")
    return _simp(v1.dot(v2) / (_norm(v1) * _norm(v2)))


def tetra_volume(vertices: tuple[sp.Matrix, sp.Matrix, sp.Matrix, sp.Matrix]) -> sp.Expr:
    """四面体体积 |(AB × AC)·AD| / 6。"""
    a, b, c, d = vertices
    return _simp(sp.Abs((b - a).cross(c - a).dot(d - a)) / 6)


def segment_length(endpoints: tuple[sp.Matrix, sp.Matrix]) -> sp.Expr:
    """线段长度 |AB|。"""
    a, b = endpoints
    return _simp(_norm(b - a))


def to_three_coords(points: dict[str, sp.Matrix], *, scale: float = 1.5) -> dict[str, list[float]]:
    """数学坐标 → three.js 坐标（y 向上），浮点，保留 6 位。"""
    return {
        n: [round(float(p[0]) * scale, 6), round(float(p[2]) * scale, 6), round(float(p[1]) * scale, 6)]
        for n, p in points.items()
    }


def latex_point_name(name: str) -> str:
    """A1 → A_1（LaTeX）。"""
    _check_name(name)
    return f"{name[0]}_{name[1]}" if len(name) == 2 else name


def latex_expr(expr: sp.Expr) -> str:
    return sp.latex(_simp(expr))


def latex_vector(v: sp.Matrix) -> str:
    return r"\left(" + ", ".join(sp.latex(_simp(c)) for c in v) + r"\right)"


def numeric_query_value(query_type: str, *, coords: list[list[float]]) -> float:
    """独立浮点复核：只用 ``math``，不走 sympy，供上层与精确解比对。

    ``coords`` 依次为该题型所需的点（数学坐标浮点），顺序同 ``QUERY_ARITY``。
    """

    def sub(p: list[float], q: list[float]) -> list[float]:
        return [p[i] - q[i] for i in range(3)]

    def dot(p: list[float], q: list[float]) -> float:
        return sum(p[i] * q[i] for i in range(3))

    def cross(p: list[float], q: list[float]) -> list[float]:
        return [p[1] * q[2] - p[2] * q[1], p[2] * q[0] - p[0] * q[2], p[0] * q[1] - p[1] * q[0]]

    def n2(p: list[float]) -> float:
        return math.sqrt(dot(p, p))

    if query_type == "line_plane_angle":
        a, b, p, q, r = coords
        v, n = sub(b, a), cross(sub(q, p), sub(r, p))
        return abs(dot(v, n)) / (n2(v) * n2(n))
    if query_type == "line_line_angle":
        a, b, c, d = coords
        v1, v2 = sub(b, a), sub(d, c)
        return abs(dot(v1, v2)) / (n2(v1) * n2(v2))
    if query_type == "point_plane_distance":
        x, p, q, r = coords
        n = cross(sub(q, p), sub(r, p))
        return abs(dot(sub(x, p), n)) / n2(n)
    if query_type == "dihedral_angle":
        a, b, c, d = coords
        n1, n2v = cross(sub(b, a), sub(c, a)), cross(sub(b, a), sub(d, a))
        # 法向量法：n1 = AB×AC、n2 = AB×AD，(u×v1)·(u×v2) = |u|²(v1·v2)，
        # 故两法向量夹角与"棱的垂线法"同号同值，又是互相独立的实现
        return dot(n1, n2v) / (n2(n1) * n2(n2v))
    if query_type == "tetra_volume":
        a, b, c, d = coords
        return abs(dot(cross(sub(b, a), sub(c, a)), sub(d, a))) / 6
    if query_type == "segment_length":
        a, b = coords
        return n2(sub(b, a))
    raise ValueError(f"unsupported query: {query_type}")
