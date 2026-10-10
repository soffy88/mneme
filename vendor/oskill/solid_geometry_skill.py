"""
立体几何解题 Skill（oskill 层）
=================================

组合 ≥2 个 oprim 原语，把一份结构化题目 ``SolidGeometrySpec`` 解成：
精确答案 + 分步解析（MathJax LaTeX）+ 3D 模型数据（three.js 坐标、棱、
可切换元素与分步高亮）。全部数值来自 oprim 的 sympy 精确计算。

依赖 oprim 原语（oprim.solid_geometry）：
- parse_dimension / build_body_points / body_topology / derive_given_points
- plane_normal / line_plane_angle_sin / line_line_angle_cos
- point_plane_distance / dihedral_angle_cos / tetra_volume / segment_length
- to_three_coords / latex_point_name / latex_expr / latex_vector

输出的 ``lesson_data`` 与 edulab ``template/lesson.html`` 的 ``__LESSON_DATA__``
格式兼容（lesson / steps / model）。
"""

from __future__ import annotations

import re
from typing import Any

import sympy as sp
from pydantic import BaseModel, ConfigDict

from oprim.solid_geometry import (
    BODY_DIMENSIONS,
    QUERY_ARITY,
    SolidGeometrySpec,
    body_topology,
    build_body_points,
    derive_given_points,
    dihedral_angle_cos,
    latex_expr,
    latex_point_name,
    latex_vector,
    line_line_angle_cos,
    line_plane_angle_sin,
    parse_dimension,
    plane_normal,
    point_plane_distance,
    segment_length,
    tetra_volume,
    to_three_coords,
)


class SolidStep(BaseModel):
    title: str
    content: str  # HTML 段落，内联 $…$ / 独立 $$…$$
    highlight: list[str]
    cameraPos: dict[str, float]


class SolidGeometrySolution(BaseModel):
    """解题结果（可 JSON 序列化）。"""

    query_type: str
    answer_latex: str
    answer_value: float
    answer_label: str
    title: str
    math_points: dict[str, list[float]]  # 数学坐标浮点（复核 / draggable 用）
    math_points_latex: dict[str, str]
    steps: list[SolidStep]
    lesson_data: dict[str, Any]

    model_config = ConfigDict(arbitrary_types_allowed=True)


_BODY_ZH = {
    "cube": "正方体",
    "cuboid": "长方体",
    "regular_quad_pyramid": "正四棱锥",
    "regular_tetrahedron": "正四面体",
}
_BODY_LABEL = {
    "cube": "ABCD-A₁B₁C₁D₁",
    "cuboid": "ABCD-A₁B₁C₁D₁",
    "regular_quad_pyramid": "P-ABCD",
    "regular_tetrahedron": "ABCD",
}
_DIM_ZH = {
    "cube": {"edge": "棱长"},
    "cuboid": {"length": "AB", "width": "AD", "height": "AA₁"},
    "regular_quad_pyramid": {"base_edge": "底面边长", "height": "高"},
    "regular_tetrahedron": {"edge": "棱长"},
}
_SETUP_ZH = {
    "cube": "以顶点 $A$ 为原点，$AB$、$AD$、$AA_1$ 所在直线分别为 $x$、$y$、$z$ 轴建立空间直角坐标系。",
    "cuboid": "以顶点 $A$ 为原点，$AB$、$AD$、$AA_1$ 所在直线分别为 $x$、$y$、$z$ 轴建立空间直角坐标系。",
    "regular_quad_pyramid": "设底面中心为 $O$（$PO\\perp$ 底面），以 $O$ 为原点，$OA$、$OB$、$OP$ 方向分别为 $x$、$y$、$z$ 轴建立空间直角坐标系。",
    "regular_tetrahedron": "把正四面体放进正方体中（四个顶点是正方体相间的四个顶点），以正方体中心为原点、平行于正方体棱的方向为坐标轴建系。",
}
_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")


def _plain(expr: sp.Expr) -> str:
    """题面纯文本数字：2*sqrt(2) → 2√2，3/2 保持。"""
    text = str(sp.nsimplify(expr)).replace("*", "")
    return re.sub(r"sqrt\((\d+)\)", r"√\1", text)


def _txt(name: str) -> str:
    return name.translate(_SUB)


def _join(names: list[str]) -> str:
    return "".join(_txt(n) for n in names)


def _tex_join(names: list[str]) -> str:
    return "".join(latex_point_name(n) for n in names)


def _cam(center: list[float], radius: float, k: tuple[float, float, float]) -> dict[str, float]:
    return {"x": round(center[0] + radius * k[0], 3), "y": round(center[1] + radius * k[1], 3), "z": round(center[2] + radius * k[2], 3)}


def _describe_given(g: Any) -> str:
    if g.kind == "midpoint":
        return f"{_txt(g.name)}为{_join(g.of)}的中点"
    if g.kind == "on_segment":
        return f"{_txt(g.name)}在线段{_join(g.of)}上，且{_txt(g.of[0])}{_txt(g.name)}={g.ratio}·{_join(g.of)}"
    return f"{_txt(g.name)}为{'、'.join(_txt(n) for n in g.of)}的重心"


def _question_zh(q: Any) -> tuple[str, str]:
    t = q.type
    if t == "line_plane_angle":
        s = f"直线{_join(q.line)}与平面{_join(q.plane)}所成角的正弦值"
    elif t == "line_line_angle":
        s = f"直线{_join(q.line)}与直线{_join(q.line2)}所成角的余弦值"
    elif t == "point_plane_distance":
        s = f"点{_txt(q.point[0])}到平面{_join(q.plane)}的距离"
    elif t == "dihedral_angle":
        s = f"二面角{_txt(q.faces[0])}-{_join(q.edge)}-{_txt(q.faces[1])}的余弦值"
    elif t == "tetra_volume":
        s = f"三棱锥{_txt(q.points[0])}-{_join(q.points[1:])}的体积"
    else:
        s = f"线段{_join(q.points)}的长度"
    return s, s


def solve_solid_geometry(spec: SolidGeometrySpec, *, scale: float = 1.5) -> SolidGeometrySolution:
    """把一道结构化立体几何题解成精确答案 + 分步解析 + 3D 模型。

    纯算法、stateless、不持久化，故为同步函数。参数非法或构型退化时抛 ``ValueError``。
    """
    q = spec.query
    for key in QUERY_ARITY[q.type]:
        q.operand(key)  # 元数校验，失败抛 ValueError

    need = BODY_DIMENSIONS[spec.body]
    extra = set(spec.dims) - set(need)
    if extra or any(k not in spec.dims for k in need):
        raise ValueError(f"{spec.body} needs dims {list(need)}")
    dims = {k: parse_dimension(spec.dims[k]) for k in need}

    pts = build_body_points(spec.body, dims=dims)
    pts = derive_given_points(pts, givens=spec.givens)

    used: list[str] = []
    for key in QUERY_ARITY[q.type]:
        for n in q.operand(key):
            if n not in pts:
                raise ValueError(f"unknown point {n}")
            if n not in used:
                used.append(n)

    topo = body_topology(spec.body)
    three = to_three_coords(pts, scale=scale)
    names = list(three)
    center = [sum(three[n][i] for n in names) / len(names) for i in range(3)]
    radius = max(max(abs(three[n][i] - center[i]) for i in range(3)) for n in names) + 1.0
    cams = [_cam(center, radius * 1.6, k) for k in ((1.0, 0.8, 1.1), (1.2, 0.6, 0.9), (0.8, 1.1, 1.2), (1.1, 0.9, 1.0))]

    elements: dict[str, dict[str, Any]] = {"Axis": {"type": "axes", "size": round(radius * 1.3, 3)}}
    for g in spec.givens:
        if g.kind in ("midpoint", "on_segment"):
            elements[f"Seg_{g.of[0]}{g.of[1]}"] = {"type": "line", "a": g.of[0], "b": g.of[1], "color": "aux", "dashed": True}

    mp_tex = {n: latex_vector(v) for n, v in pts.items()}
    coord_list = ", ".join(f"{latex_point_name(n)}{mp_tex[n]}" for n in used)
    dim_text = "，".join(
        f"{_DIM_ZH[spec.body][k]}={_plain(dims[k])}" if spec.body == "cuboid" else f"{_DIM_ZH[spec.body][k]}为{_plain(dims[k])}"
        for k in need
    )
    given_text = "".join(f"，{_describe_given(g)}" for g in spec.givens)
    ask, label = _question_zh(q)
    title = f"{_BODY_ZH[spec.body]}{_BODY_LABEL[spec.body]}中，{dim_text}{given_text}，求{ask}。"

    steps: list[SolidStep] = [
        SolidStep(
            title="建立空间直角坐标系",
            content=f"<p>{_SETUP_ZH[spec.body]}</p><p>相关点的坐标：</p>$${coord_list}$$",
            highlight=["Axis"],
            cameraPos=cams[0],
        )
    ]
    if spec.givens:
        lines = "".join(
            f"<p>{_describe_given(g)}，得 ${latex_point_name(g.name)}{mp_tex[g.name]}$。</p>" for g in spec.givens
        )
        steps.append(
            SolidStep(
                title="求构造点坐标",
                content=lines,
                highlight=["Axis", *[k for k in elements if k.startswith("Seg_")]],
                cameraPos=cams[1],
            )
        )

    def vec_tex(a: str, b: str) -> str:
        return r"\overrightarrow{" + latex_point_name(a) + latex_point_name(b) + "}"

    if q.type in ("line_plane_angle", "point_plane_distance"):
        pl = q.operand("plane")
        raw, n = plane_normal((pts[pl[0]], pts[pl[1]], pts[pl[2]]))
        plane_key = f"Plane_{''.join(pl)}"
        elements[plane_key] = {"type": "plane", "pts": pl}
        n_three = [float(n[0]), float(n[2]), float(n[1])]
        n_len = sum(c * c for c in n_three) ** 0.5
        elements["Normal_Vector"] = {
            "type": "arrow", "origin": pl[0], "dir": [round(c / n_len, 6) for c in n_three],
            "length": round(radius * 0.9, 3), "color": "normal",
        }
        normal_step = SolidStep(
            title=f"求平面 {_join(pl)} 的法向量",
            content=(
                f"<p>取 ${vec_tex(pl[0], pl[1])}={latex_vector(pts[pl[1]] - pts[pl[0]])}$，"
                f"${vec_tex(pl[0], pl[2])}={latex_vector(pts[pl[2]] - pts[pl[0]])}$。</p>"
                f"<p>设法向量 $\\vec n$ 与二者都垂直，由叉积得 ${latex_vector(raw)}$，约简取</p>"
                f"$$\\vec n={latex_vector(n)}$$"
            ),
            highlight=["Axis", plane_key, "Normal_Vector"],
            cameraPos=cams[2],
        )
        if q.type == "line_plane_angle":
            ln = q.operand("line")
            v = pts[ln[1]] - pts[ln[0]]
            line_key = f"Line_{''.join(ln)}"
            elements[line_key] = {"type": "line", "a": ln[0], "b": ln[1], "color": "emphasis", "depthTest": False}
            ans = line_plane_angle_sin(v, normal=n)
            steps.append(SolidStep(
                title=f"求直线 {_join(ln)} 的方向向量",
                content=f"$${vec_tex(ln[0], ln[1])}={latex_point_name(ln[1])}-{latex_point_name(ln[0])}={latex_vector(v)}$$",
                highlight=["Axis", line_key], cameraPos=cams[1],
            ))
            normal_step.highlight.append(line_key)
            steps.append(normal_step)
            steps.append(SolidStep(
                title="代入线面角公式",
                content=(
                    "<p>设所成角为 $\\theta$，则 $\\sin\\theta=\\dfrac{|\\vec v\\cdot\\vec n|}{|\\vec v|\\,|\\vec n|}$。</p>"
                    f"$$\\vec v\\cdot\\vec n={latex_expr(v.dot(n))},\\quad |\\vec v|={latex_expr(sp.sqrt(v.dot(v)))},\\quad |\\vec n|={latex_expr(sp.sqrt(n.dot(n)))}$$"
                    f"$$\\sin\\theta={latex_expr(ans)}$$"
                ),
                highlight=["Axis", line_key, plane_key, "Normal_Vector"], cameraPos=cams[3],
            ))
        else:
            x = q.operand("point")[0]
            w = pts[x] - pts[pl[0]]
            seg_key = f"Line_{pl[0]}{x}"
            elements[seg_key] = {"type": "line", "a": pl[0], "b": x, "color": "emphasis", "depthTest": False}
            ans = point_plane_distance(pts[x], plane_point=pts[pl[0]], normal=n)
            steps.append(normal_step)
            steps.append(SolidStep(
                title="代入点面距离公式",
                content=(
                    f"<p>取平面内一点 ${latex_point_name(pl[0])}$，${vec_tex(pl[0], x)}={latex_vector(w)}$。</p>"
                    f"$$d=\\dfrac{{|{vec_tex(pl[0], x)}\\cdot\\vec n|}}{{|\\vec n|}}=\\dfrac{{{latex_expr(sp.Abs(w.dot(n)))}}}{{{latex_expr(sp.sqrt(n.dot(n)))}}}={latex_expr(ans)}$$"
                ),
                highlight=["Axis", plane_key, "Normal_Vector", seg_key], cameraPos=cams[3],
            ))
    elif q.type == "line_line_angle":
        l1, l2 = q.operand("line"), q.operand("line2")
        d1, d2 = pts[l1[1]] - pts[l1[0]], pts[l2[1]] - pts[l2[0]]
        k1, k2 = f"Line_{''.join(l1)}", f"Line_{''.join(l2)}"
        elements[k1] = {"type": "line", "a": l1[0], "b": l1[1], "color": "emphasis", "depthTest": False}
        elements[k2] = {"type": "line", "a": l2[0], "b": l2[1], "color": "normal", "depthTest": False}
        ans = line_line_angle_cos(d1, other=d2)
        steps.append(SolidStep(
            title="求两直线的方向向量",
            content=f"$${vec_tex(*l1)}={latex_vector(d1)},\\quad {vec_tex(*l2)}={latex_vector(d2)}$$",
            highlight=["Axis", k1, k2], cameraPos=cams[1],
        ))
        steps.append(SolidStep(
            title="代入夹角公式",
            content=(
                "<p>两直线所成角 $\\theta\\in(0,\\tfrac{\\pi}{2}]$，$\\cos\\theta=\\dfrac{|\\vec a\\cdot\\vec b|}{|\\vec a|\\,|\\vec b|}$。</p>"
                f"$$\\cos\\theta=\\dfrac{{{latex_expr(sp.Abs(d1.dot(d2)))}}}{{{latex_expr(sp.sqrt(d1.dot(d1)))}\\cdot{latex_expr(sp.sqrt(d2.dot(d2)))}}}={latex_expr(ans)}$$"
            ),
            highlight=["Axis", k1, k2], cameraPos=cams[3],
        ))
    elif q.type == "dihedral_angle":
        ed, fc = q.operand("edge"), q.operand("faces")
        k1, k2 = f"Plane_{ed[0]}{ed[1]}{fc[0]}", f"Plane_{ed[0]}{ed[1]}{fc[1]}"
        ek = f"Line_{''.join(ed)}"
        elements[k1] = {"type": "plane", "pts": [ed[0], ed[1], fc[0]]}
        elements[k2] = {"type": "plane", "pts": [ed[0], ed[1], fc[1]]}
        elements[ek] = {"type": "line", "a": ed[0], "b": ed[1], "color": "emphasis", "depthTest": False}
        _, n1 = plane_normal((pts[ed[0]], pts[ed[1]], pts[fc[0]]))
        _, n2 = plane_normal((pts[ed[0]], pts[ed[1]], pts[fc[1]]))
        ans = dihedral_angle_cos((pts[ed[0]], pts[ed[1]]), faces=(pts[fc[0]], pts[fc[1]]))
        steps.append(SolidStep(
            title="求两个半平面的法向量",
            content=f"<p>平面 {_join([ed[0], ed[1], fc[0]])} 的一个法向量 $\\vec{{n_1}}={latex_vector(n1)}$，平面 {_join([ed[0], ed[1], fc[1]])} 的一个法向量 $\\vec{{n_2}}={latex_vector(n2)}$。</p>",
            highlight=["Axis", ek, k1, k2], cameraPos=cams[2],
        ))
        sign = "锐" if ans > 0 else ("直" if ans == 0 else "钝")
        steps.append(SolidStep(
            title="判断锐钝并求余弦",
            content=(
                f"<p>$|\\cos\\langle\\vec{{n_1}},\\vec{{n_2}}\\rangle|={latex_expr(sp.Abs(ans))}$。"
                f"在棱 ${_tex_join(ed)}$ 两侧各作垂线可判断该二面角为{sign}角，所以</p>"
                f"$$\\cos\\theta={latex_expr(ans)}$$"
            ),
            highlight=["Axis", ek, k1, k2], cameraPos=cams[3],
        ))
    elif q.type == "tetra_volume":
        a, b, c, d = (pts[n] for n in q.operand("points"))
        names4 = q.operand("points")
        for i, j in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)):
            elements[f"Line_{names4[i]}{names4[j]}"] = {"type": "line", "a": names4[i], "b": names4[j], "color": "emphasis", "depthTest": False}
        ans = tetra_volume((a, b, c, d))
        cr = (b - a).cross(c - a)
        steps.append(SolidStep(
            title="用向量混合积求体积",
            content=(
                f"<p>$V=\\dfrac16\\left|({vec_tex(names4[0], names4[1])}\\times{vec_tex(names4[0], names4[2])})\\cdot{vec_tex(names4[0], names4[3])}\\right|$。</p>"
                f"$${vec_tex(names4[0], names4[1])}\\times{vec_tex(names4[0], names4[2])}={latex_vector(cr)},\\quad {vec_tex(names4[0], names4[3])}={latex_vector(d - a)}$$"
                f"$$V=\\dfrac16\\cdot{latex_expr(sp.Abs(cr.dot(d - a)))}={latex_expr(ans)}$$"
            ),
            highlight=["Axis", *[k for k in elements if k.startswith("Line_")]], cameraPos=cams[3],
        ))
    else:  # segment_length
        a, b = q.operand("points")
        k = f"Line_{a}{b}"
        elements[k] = {"type": "line", "a": a, "b": b, "color": "emphasis", "depthTest": False}
        ans = segment_length((pts[a], pts[b]))
        steps.append(SolidStep(
            title="用两点间距离公式",
            content=f"$$|{_tex_join([a, b])}|=|{vec_tex(a, b)}|=\\left|{latex_vector(pts[b] - pts[a])}\\right|={latex_expr(ans)}$$",
            highlight=["Axis", k], cameraPos=cams[3],
        ))

    ans_tex = latex_expr(ans)
    steps.append(SolidStep(
        title="结论",
        content=f"<p>所以{label}为 ${ans_tex}$。</p>",
        highlight=steps[-1].highlight,
        cameraPos=cams[0],
    ))

    spheres = list(dict.fromkeys([*topo["spheres"], *[g.name for g in spec.givens]]))
    lesson_data = {
        "lesson": {
            "language": spec.language,
            "meta": "交互解题 · 立体几何",
            "title": title,
            "answerLabel": label,
            "answerValue": f"${ans_tex}$",
        },
        "steps": [s.model_dump() for s in steps],
        "model": {
            "points": three,
            "spheres": spheres,
            "edges": topo["edges"],
            "elements": elements,
            "target": [round(c, 3) for c in center],
            "initialCamera": [cams[0]["x"], cams[0]["y"], cams[0]["z"]],
        },
    }
    return SolidGeometrySolution(
        query_type=q.type,
        answer_latex=ans_tex,
        answer_value=float(ans),
        answer_label=label,
        title=title,
        math_points={n: [float(c) for c in v] for n, v in pts.items()},
        math_points_latex=mp_tex,
        steps=steps,
        lesson_data=lesson_data,
    )
