"""Animator（Layer 4）：确定性步骤动画时间线（DeepTutor Animator 对标，替代 Manim）。

DeepTutor 的 Animator 让 LLM 写 Manim 代码、服务端执行渲染视频。Mneme 不这样做：

- **零代码执行**：本模块只调用既有确定性内核（立体几何 / 圆锥曲线弦 / 化学配平 /
  visualize 的 ``kernel_to_plot2d``），把它们的结构化输出编排成一份**纯数据**时间线
  （``spec_version = mneme.anim/1``）：图元白名单 + 关键帧。没有任何字符串会被当作代码
  执行——服务端不 eval/exec，客户端播放器（``/v1/edu-assets/mneme-animator-1/player.js``）
  只按白名单图元类型 ``createElementNS`` 绘制 SVG，文字一律 ``textContent``。
- **确定性**：同一输入 → 逐字节相同的时间线（浮点统一四舍五入到 4 位，fingerprint
  为规范 JSON 的 sha256 前 24 位）。
- **不碰门控**：纯计算、无 DB、不调用 LLM，不写掌握度。

时间线结构::

    {spec_version, kind, title, answer{label, latex}, canvas{mode, view, camera?},
     shapes[{id, type, ...}], frames[{title, caption, readout?, show[], highlight[],
     set{shape_id: {attr: value}}, camera?, duration_ms}], fingerprint}
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SPEC_VERSION = "mneme.anim/1"
AnimKind = Literal[
    "solid_geometry", "conic_chord", "equation_balance", "function_graph"
]
KINDS: tuple[str, ...] = (
    "solid_geometry",
    "conic_chord",
    "equation_balance",
    "function_graph",
)

# 客户端播放器认识的全部图元类型与属性——validate_spec 用它做白名单。
SHAPE_TYPES: dict[str, frozenset[str]] = {
    "point": frozenset({"at", "label", "color", "r"}),
    "segment": frozenset({"from", "to", "color", "dashed", "width"}),
    "arrow": frozenset({"from", "to", "color", "label"}),
    "polyline": frozenset({"pts", "color", "width", "dashed"}),
    "polygon": frozenset({"pts", "color", "opacity"}),
    "circle": frozenset({"at", "radius", "color", "opacity"}),
    "text": frozenset({"at", "text", "color", "size", "anchor"}),
    "bar": frozenset({"at", "value", "max", "label", "color", "width"}),
}
SETTABLE = frozenset({"at", "from", "to", "pts", "text", "value", "label"})
PALETTE = frozenset(
    {
        "ink",
        "muted",
        "axis",
        "curve",
        "line",
        "given",
        "emphasis",
        "aux",
        "normal",
        "plane",
        "ptA",
        "ptB",
        "vecA",
        "vecB",
        "left",
        "right",
        "good",
        "bad",
    }
)
MAX_FRAMES = 80
MAX_SHAPES = 400
MAX_POINTS = 600
MAX_TEXT = 4000
_ID = re.compile(r"^[A-Za-z0-9_\-]{1,48}$")


class AnimateError(ValueError):
    """动画参数不合法或内核无法求解（→ 422）。"""


class AnimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AnimKind
    params: dict[str, Any] = Field(default_factory=dict)


class FunctionGraphParams(BaseModel):
    """visualize 模块的确定性曲线：表达式经 obase SymPyRuntime（AST 白名单 + 沙箱）解析。"""

    model_config = ConfigDict(extra="forbid")

    expression: str = Field(min_length=1, max_length=120)
    x_min: float = Field(default=-5.0, ge=-1000, le=1000)
    x_max: float = Field(default=5.0, ge=-1000, le=1000)


# ── 通用工具 ──────────────────────────────────────────────────────────────────


def _r(x: float) -> float:
    v = round(float(x), 4)
    return 0.0 if v == 0 else v  # 去掉 -0.0，保证逐字节确定


def _canon(obj: Any) -> Any:
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise AnimateError("non-finite number in animation")
        return _r(obj)
    if isinstance(obj, dict):
        return {str(k): _canon(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canon(v) for v in obj]
    raise AnimateError(f"unsupported value in animation spec: {type(obj).__name__}")


def _finish(spec: dict[str, Any]) -> dict[str, Any]:
    body = _canon({k: v for k, v in spec.items() if k != "fingerprint"})
    body["spec_version"] = SPEC_VERSION
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    body["fingerprint"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]
    validate_spec(body)
    return body


def _frame(
    title: str,
    caption: str = "",
    *,
    show: list[str],
    highlight: list[str] | None = None,
    set_: dict[str, dict[str, Any]] | None = None,
    readout: str = "",
    camera: dict[str, float] | None = None,
    duration_ms: int = 1600,
) -> dict[str, Any]:
    f: dict[str, Any] = {
        "title": title,
        "caption": caption,
        "show": show,
        "highlight": highlight or [],
        "set": set_ or {},
        "duration_ms": duration_ms,
    }
    if readout:
        f["readout"] = readout
    if camera is not None:
        f["camera"] = camera
    return f


def validate_spec(spec: dict[str, Any]) -> None:
    """时间线白名单校验：只允许已知图元/属性/颜色、纯数据（无函数、无代码字段）。

    这是"无代码执行"保证的服务端一半：任何不在白名单里的东西都过不去，播放器
    也就永远拿不到它不认识的指令。
    """
    if spec.get("spec_version") != SPEC_VERSION:
        raise AnimateError("bad spec_version")
    if spec.get("kind") not in KINDS:
        raise AnimateError("bad kind")
    allowed_top = {
        "spec_version",
        "kind",
        "title",
        "answer",
        "canvas",
        "shapes",
        "frames",
        "fingerprint",
    }
    extra = set(spec) - allowed_top
    if extra:
        raise AnimateError(f"unexpected top-level keys: {sorted(extra)}")
    canvas = spec.get("canvas") or {}
    if canvas.get("mode") not in ("2d", "3d"):
        raise AnimateError("bad canvas mode")
    view = canvas.get("view")
    if not (
        isinstance(view, list)
        and len(view) == 4
        and all(isinstance(v, (int, float)) for v in view)
    ):
        raise AnimateError("bad canvas view")
    shapes = spec.get("shapes")
    frames = spec.get("frames")
    if not isinstance(shapes, list) or not (0 < len(shapes) <= MAX_SHAPES):
        raise AnimateError("bad shapes")
    if not isinstance(frames, list) or not (0 < len(frames) <= MAX_FRAMES):
        raise AnimateError("bad frames")
    ids: set[str] = set()
    for s in shapes:
        if not isinstance(s, dict):
            raise AnimateError("shape must be an object")
        sid, stype = s.get("id"), s.get("type")
        if not isinstance(sid, str) or not _ID.match(sid) or sid in ids:
            raise AnimateError(f"bad shape id: {sid!r}")
        if stype not in SHAPE_TYPES:
            raise AnimateError(f"shape type not allowed: {stype!r}")
        bad = set(s) - {"id", "type"} - SHAPE_TYPES[stype]
        if bad:
            raise AnimateError(f"shape {sid}: attributes not allowed: {sorted(bad)}")
        if "color" in s and s["color"] not in PALETTE:
            raise AnimateError(f"shape {sid}: color not in palette")
        pts = s.get("pts")
        if pts is not None and (not isinstance(pts, list) or len(pts) > MAX_POINTS):
            raise AnimateError(f"shape {sid}: too many points")
        ids.add(sid)
    for f in frames:
        if not isinstance(f, dict):
            raise AnimateError("frame must be an object")
        bad = set(f) - {
            "title",
            "caption",
            "readout",
            "show",
            "highlight",
            "set",
            "camera",
            "duration_ms",
        }
        if bad:
            raise AnimateError(f"frame keys not allowed: {sorted(bad)}")
        for key in ("show", "highlight"):
            unknown = [x for x in f.get(key, []) if x not in ids]
            if unknown:
                raise AnimateError(f"frame references unknown shapes: {unknown[:3]}")
        for sid, attrs in (f.get("set") or {}).items():
            if sid not in ids or not isinstance(attrs, dict) or set(attrs) - SETTABLE:
                raise AnimateError(f"frame set not allowed for {sid!r}")
        for key in ("title", "caption", "readout"):
            v = f.get(key, "")
            if not isinstance(v, str) or len(v) > MAX_TEXT:
                raise AnimateError(f"frame {key} must be a short string")
        d = f.get("duration_ms", 0)
        if not isinstance(d, int) or not (0 <= d <= 20000):
            raise AnimateError("bad duration")
    _no_callables(spec)


def _no_callables(obj: Any) -> None:
    if callable(obj):
        raise AnimateError("callable in spec")
    if isinstance(obj, dict):
        for v in obj.values():
            _no_callables(v)
    elif isinstance(obj, list):
        for v in obj:
            _no_callables(v)


_TEX_SIMPLE = [
    (re.compile(r"\\sqrt\{([^{}]*)\}"), r"√(\1)"),
    (re.compile(r"\\frac\{([^{}]*)\}\{([^{}]*)\}"), r"(\1)/(\2)"),
    (re.compile(r"\\(left|right)"), ""),
    (re.compile(r"\\[,;! ]"), " "),
    (re.compile(r"[{}]"), ""),
]


def _plain_tex(s: str) -> str:
    """measure 标签等极短 LaTeX → 纯文本（SVG text 用，避免在图里塞 HTML）。"""
    out = s
    for _ in range(3):
        for pat, rep in _TEX_SIMPLE:
            out = pat.sub(rep, out)
    return out.replace("\\", "")[:40]


# ── 立体几何 ──────────────────────────────────────────────────────────────────


def _cam_from(
    pos: dict[str, Any] | list[float], target: list[float]
) -> dict[str, float]:
    if isinstance(pos, dict):
        x, y, z = float(pos.get("x", 0)), float(pos.get("y", 0)), float(pos.get("z", 0))
    else:
        x, y, z = (float(v) for v in pos[:3])
    dx, dy, dz = x - target[0], y - target[1], z - target[2]
    az = math.degrees(math.atan2(dx, dz))
    el = math.degrees(math.atan2(dy, math.hypot(dx, dz)))
    return {"azimuth": _r(az), "elevation": _r(el)}


_SOLID_COLOR = {
    "aux": "aux",
    "emphasis": "emphasis",
    "normal": "normal",
    "plane": "plane",
}


def _solid_timeline(solution: dict[str, Any]) -> dict[str, Any]:
    lesson = solution["lesson_data"]
    model = lesson.get("model") or {}
    points: dict[str, list[float]] = {
        k: [float(c) for c in v] for k, v in (model.get("points") or {}).items()
    }
    target = [float(c) for c in (model.get("target") or [0.0, 0.0, 0.0])]

    def pt(ref: Any) -> list[float] | None:
        if isinstance(ref, str):
            return points.get(ref)
        if isinstance(ref, (list, tuple)) and len(ref) == 3:
            return [float(c) for c in ref]
        return None

    shapes: list[dict[str, Any]] = []
    base: list[str] = []
    for i, e in enumerate(model.get("edges") or []):
        a, b = pt(e.get("a")), pt(e.get("b"))
        if a is None or b is None:
            continue
        sid = f"edge_{i}"
        shapes.append(
            {
                "id": sid,
                "type": "segment",
                "from": a,
                "to": b,
                "color": "ink",
                "dashed": bool(e.get("dashed")),
            }
        )
        base.append(sid)
    for name in model.get("spheres") or list(points):
        p = pt(name)
        if p is None:
            continue
        sid = f"pt_{name}"
        shapes.append(
            {"id": sid, "type": "point", "at": p, "label": str(name), "color": "ink"}
        )
        base.append(sid)

    element_ids: dict[str, list[str]] = {}
    for name, el in (model.get("elements") or {}).items():
        etype = el.get("type")
        ids: list[str] = []
        color = _SOLID_COLOR.get(str(el.get("color", "")), "emphasis")
        if etype == "line":
            a, b = pt(el.get("a")), pt(el.get("b"))
            if a and b:
                ids.append(f"el_{name}")
                shapes.append(
                    {
                        "id": ids[-1],
                        "type": "segment",
                        "from": a,
                        "to": b,
                        "color": color,
                        "dashed": bool(el.get("dashed")),
                        "width": 3,
                    }
                )
        elif etype == "plane":
            pts = [pt(p) for p in el.get("pts") or []]
            if pts and all(p is not None for p in pts):
                ids.append(f"el_{name}")
                shapes.append(
                    {
                        "id": ids[-1],
                        "type": "polygon",
                        "pts": pts,
                        "color": "plane",
                        "opacity": 0.25,
                    }
                )
        elif etype == "arrow":
            o = pt(el.get("origin"))
            d = el.get("dir") or [0, 1, 0]
            n = math.sqrt(sum(float(c) ** 2 for c in d)) or 1.0
            length = float(el.get("length") or 1.5)
            if o:
                tip = [o[k] + float(d[k]) / n * length for k in range(3)]
                ids.append(f"el_{name}")
                shapes.append(
                    {
                        "id": ids[-1],
                        "type": "arrow",
                        "from": o,
                        "to": tip,
                        "color": "normal",
                    }
                )
        elif etype == "axes":
            size = float(el.get("size") or 3)
            for k, lab in enumerate(("x", "y", "z")):
                tip = [0.0, 0.0, 0.0]
                tip[k] = size
                ids.append(f"el_{name}_{lab}")
                shapes.append(
                    {
                        "id": ids[-1],
                        "type": "arrow",
                        "from": [0.0, 0.0, 0.0],
                        "to": tip,
                        "color": "axis",
                        "label": lab,
                    }
                )
        elif etype == "sphere":
            c = pt(el.get("center"))
            if c:
                ids.append(f"el_{name}")
                shapes.append(
                    {
                        "id": ids[-1],
                        "type": "circle",
                        "at": c,
                        "radius": float(el.get("radius") or 1),
                        "color": "plane",
                        "opacity": 0.15,
                    }
                )
        elif etype == "measure":
            a, b = pt(el.get("a")), pt(el.get("b"))
            if a and b:
                mid = [(a[k] + b[k]) / 2 for k in range(3)]
                ids.append(f"el_{name}")
                shapes.append(
                    {
                        "id": ids[-1],
                        "type": "text",
                        "at": mid,
                        "text": _plain_tex(str(el.get("label", ""))),
                        "color": "emphasis",
                        "size": 13,
                    }
                )
        if ids:
            element_ids[str(name)] = ids

    init_cam = _cam_from(model.get("initialCamera") or [5, 4, 5], target)
    meta = lesson.get("lesson") or {}
    frames = [
        _frame(
            "题目",
            f"<p>{_esc(solution.get('title', ''))}</p>",
            show=list(base),
            camera=init_cam,
            duration_ms=2200,
        )
    ]
    for step in lesson.get("steps") or []:
        hl: list[str] = []
        for name in step.get("highlight") or []:
            hl.extend(element_ids.get(str(name), []))
        cam = _cam_from(step["cameraPos"], target) if step.get("cameraPos") else None
        frames.append(
            _frame(
                str(step.get("title", "")),
                str(step.get("content", "")),
                show=base + hl,
                highlight=hl,
                camera=cam,
                duration_ms=2600,
            )
        )
    every = [
        i for ids in element_ids.values() for i in ids if not i.startswith("el_Axis")
    ]
    frames.append(
        _frame(
            "答案",
            f"<p>{_esc(str(meta.get('answerLabel', solution.get('answer_label', ''))))}：${solution['answer_latex']}$</p>",
            show=base + every,
            highlight=every,
            camera=init_cam,
            duration_ms=2600,
        )
    )
    extent = max([abs(c) for p in points.values() for c in p] + [1.0]) * 1.6
    return {
        "kind": "solid_geometry",
        "title": solution.get("title", ""),
        "answer": {
            "label": solution.get("answer_label", ""),
            "latex": solution.get("answer_latex", ""),
        },
        "canvas": {
            "mode": "3d",
            "view": [-extent, extent, -extent, extent],
            "target": target,
        },
        "shapes": shapes,
        "frames": frames,
    }


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── 圆锥曲线弦 ────────────────────────────────────────────────────────────────


def _conic_coeffs(c: dict[str, Any]) -> tuple[float, float, float, float, float]:
    """A x² + C y² + D x + E y + F = 0（中心在原点，与画板数据一致）。"""
    kind = c.get("kind")
    axis = c.get("axis", "x")
    if kind == "ellipse":
        a, b = float(c["a"]), float(c["b"])
        return 1 / a**2, 1 / b**2, 0.0, 0.0, -1.0
    if kind == "hyperbola":
        a, b = float(c["a"]), float(c["b"])
        if axis == "y":
            return -1 / b**2, 1 / a**2, 0.0, 0.0, -1.0
        return 1 / a**2, -1 / b**2, 0.0, 0.0, -1.0
    if kind == "parabola":
        p = float(c["p"])
        if axis == "y":
            return 1.0, 0.0, 0.0, -2 * p, 0.0
        return 0.0, 1.0, -2 * p, 0.0, 0.0
    raise AnimateError(f"unsupported conic kind: {kind}")


def _conic_polylines(
    c: dict[str, Any], xr: list[float], yr: list[float]
) -> list[list[list[float]]]:
    kind, axis = c.get("kind"), c.get("axis", "x")
    n = 160
    if kind == "ellipse":
        a, b = float(c["a"]), float(c["b"])
        return [
            [
                [a * math.cos(2 * math.pi * i / n), b * math.sin(2 * math.pi * i / n)]
                for i in range(n + 1)
            ]
        ]

    def inside(p: list[float]) -> bool:
        return xr[0] <= p[0] <= xr[1] and yr[0] <= p[1] <= yr[1]

    lines: list[list[list[float]]] = []
    if kind == "parabola":
        p = float(c["p"])
        if axis == "y":
            raw = [
                [x, x * x / (2 * p)]
                for x in (xr[0] + (xr[1] - xr[0]) * i / n for i in range(n + 1))
            ]
        else:
            raw = [
                [y * y / (2 * p), y]
                for y in (yr[0] + (yr[1] - yr[0]) * i / n for i in range(n + 1))
            ]
        lines.append([q for q in raw if inside(q)])
    elif kind == "hyperbola":
        a, b = float(c["a"]), float(c["b"])
        for sign in (1.0, -1.0):
            if axis == "y":
                raw = [
                    [x, sign * a * math.sqrt(1 + x * x / b**2)]
                    for x in (xr[0] + (xr[1] - xr[0]) * i / n for i in range(n + 1))
                ]
            else:
                raw = [
                    [sign * a * math.sqrt(1 + y * y / b**2), y]
                    for y in (yr[0] + (yr[1] - yr[0]) * i / n for i in range(n + 1))
                ]
            lines.append([q for q in raw if inside(q)])
    return [ln for ln in lines if len(ln) >= 2]


def chord_points(
    coeffs: tuple[float, float, float, float, float],
    through: list[float],
    theta_deg: float,
) -> tuple[list[float], list[float]] | None:
    """过 through、倾斜角 θ 的直线与曲线的两个交点（按参数 t 升序）；不足两点 → None。"""
    A, C, D, E, F = coeffs
    fx, fy = through
    th = math.radians(theta_deg)
    cx, sy = math.cos(th), math.sin(th)
    qa = A * cx * cx + C * sy * sy
    qb = 2 * A * fx * cx + 2 * C * fy * sy + D * cx + E * sy
    qc = A * fx * fx + C * fy * fy + D * fx + E * fy + F
    if abs(qa) < 1e-9:
        return None
    disc = qb * qb - 4 * qa * qc
    if disc <= 1e-12:
        return None
    r = math.sqrt(disc)
    t1, t2 = sorted(((-qb - r) / (2 * qa), (-qb + r) / (2 * qa)))
    return [fx + t1 * cx, fy + t1 * sy], [fx + t2 * cx, fy + t2 * sy]


def chord_target_value(
    target: str, a: list[float], b: list[float], vertex: list[float] | None
) -> float:
    if target == "chord_length":
        return math.hypot(a[0] - b[0], a[1] - b[1])
    v = vertex or [0.0, 0.0]
    ua, ub = [a[0] - v[0], a[1] - v[1]], [b[0] - v[0], b[1] - v[1]]
    if target in ("dot_product", "fixed_value_dot"):
        return ua[0] * ub[0] + ua[1] * ub[1]
    if target == "triangle_area":
        return abs(ua[0] * ub[1] - ua[1] * ub[0]) / 2
    raise AnimateError(f"unsupported target: {target}")


_TARGET_NAME = {
    "chord_length": "|AB|",
    "dot_product": "数量积",
    "fixed_value_dot": "数量积",
    "triangle_area": "面积",
}

SWEEP_ANGLES: tuple[float, ...] = tuple(float(a) for a in range(5, 180, 10))


def _conic_timeline(solution: dict[str, Any]) -> dict[str, Any]:
    board_data = solution["board_data"]
    board = board_data.get("board") or {}
    view = board.get("view") or {}
    xr = [float(v) for v in view.get("xRange", [-5, 5])]
    yr = [float(v) for v in view.get("yRange", [-5, 5])]
    conic = (board.get("conics") or [{}])[0]
    coeffs = _conic_coeffs(conic)
    through = [float(v) for v in solution["through"]]
    vertex = [float(v) for v in solution["vertex"]] if solution.get("vertex") else None
    target = str(solution["target"])

    shapes: list[dict[str, Any]] = [
        {
            "id": "axis_x",
            "type": "arrow",
            "from": [xr[0], 0.0],
            "to": [xr[1], 0.0],
            "color": "axis",
            "label": "x",
        },
        {
            "id": "axis_y",
            "type": "arrow",
            "from": [0.0, yr[0]],
            "to": [0.0, yr[1]],
            "color": "axis",
            "label": "y",
        },
    ]
    base = ["axis_x", "axis_y"]
    for i, line in enumerate(_conic_polylines(conic, xr, yr)):
        shapes.append(
            {
                "id": f"curve_{i}",
                "type": "polyline",
                "pts": line,
                "color": "curve",
                "width": 2.5,
            }
        )
        base.append(f"curve_{i}")
    for name, p in (board.get("points") or {}).items():
        sid = f"pt_{name}"
        shapes.append(
            {
                "id": sid,
                "type": "point",
                "at": [float(c) for c in p["xy"]],
                "label": str(p.get("label", name)),
                "color": "given",
            }
        )
        base.append(sid)

    def geometry_at(theta: float) -> tuple[dict[str, dict[str, Any]], float] | None:
        hit = chord_points(coeffs, through, theta)
        if hit is None:
            return None
        a, b = hit
        span = max(xr[1] - xr[0], yr[1] - yr[0])
        th = math.radians(theta)
        d = [math.cos(th) * span, math.sin(th) * span]
        sets: dict[str, dict[str, Any]] = {
            "line_l": {
                "from": [through[0] - d[0], through[1] - d[1]],
                "to": [through[0] + d[0], through[1] + d[1]],
            },
            "pt_A": {"at": a},
            "pt_B": {"at": b},
            "chord": {"from": a, "to": b},
        }
        if vertex is not None:
            sets["vec_A"] = {"from": vertex, "to": a}
            sets["vec_B"] = {"from": vertex, "to": b}
        return sets, chord_target_value(target, a, b, vertex)

    start = geometry_at(45.0) or next(
        (g for g in (geometry_at(t) for t in SWEEP_ANGLES) if g), None
    )
    if start is None:
        raise AnimateError("这条弦在任何倾斜角下都与曲线没有两个交点")
    s0 = start[0]
    shapes += [
        {
            "id": "line_l",
            "type": "segment",
            "from": s0["line_l"]["from"],
            "to": s0["line_l"]["to"],
            "color": "line",
            "width": 1.5,
        },
        {
            "id": "chord",
            "type": "segment",
            "from": s0["chord"]["from"],
            "to": s0["chord"]["to"],
            "color": "emphasis",
            "width": 3,
        },
        {
            "id": "pt_A",
            "type": "point",
            "at": s0["pt_A"]["at"],
            "label": "A",
            "color": "ptA",
        },
        {
            "id": "pt_B",
            "type": "point",
            "at": s0["pt_B"]["at"],
            "label": "B",
            "color": "ptB",
        },
    ]
    moving = ["line_l", "chord", "pt_A", "pt_B"]
    if vertex is not None:
        shapes += [
            {
                "id": "vec_A",
                "type": "arrow",
                "from": vertex,
                "to": s0["pt_A"]["at"],
                "color": "vecA",
            },
            {
                "id": "vec_B",
                "type": "arrow",
                "from": vertex,
                "to": s0["pt_B"]["at"],
                "color": "vecB",
            },
        ]
        moving += ["vec_A", "vec_B"]

    name = _TARGET_NAME.get(target, target)
    frames = [
        _frame(
            "题目",
            str(solution.get("problem_html", "")),
            show=list(base),
            duration_ms=2400,
        )
    ]
    for i, step in enumerate(board_data.get("steps") or []):
        frames.append(
            _frame(
                str(step.get("title", "")),
                str(step.get("content", "")),
                show=base + moving,
                highlight=["chord"] if i == 0 else [],
                set_=s0,
                duration_ms=2600,
            )
        )
    sweep_values: list[float] = []
    for theta in SWEEP_ANGLES:
        g = geometry_at(theta)
        if g is None:
            continue
        sets, value = g
        sweep_values.append(value)
        frames.append(
            _frame(
                f"转动直线 l：θ = {theta:g}°",
                f"<p>倾斜角 $\\theta={theta:g}^\\circ$ 时，{name} $\\approx {value:.4f}$。答案：${solution['answer_latex']}$</p>",
                show=base + moving,
                highlight=["chord"],
                set_=sets,
                readout=f"θ = {theta:g}°   {name} ≈ {value:.4f}",
                duration_ms=700,
            )
        )
    frames.append(
        _frame(
            "答案",
            f"<p>{_esc(str(solution.get('answer_label', '')))}：${solution['answer_latex']}$</p>"
            f"<p>扫描到的数值范围约为 [{min(sweep_values):.4f}, {max(sweep_values):.4f}]，与精确答案一致。</p>"
            if sweep_values
            else f"<p>{_esc(str(solution.get('answer_label', '')))}：${solution['answer_latex']}$</p>",
            show=base + moving,
            highlight=["chord"],
            set_=s0,
            duration_ms=2600,
        )
    )
    return {
        "kind": "conic_chord",
        "title": solution.get("title", ""),
        "answer": {
            "label": solution.get("answer_label", ""),
            "latex": solution.get("answer_latex", ""),
        },
        "canvas": {"mode": "2d", "view": [xr[0], xr[1], yr[0], yr[1]]},
        "shapes": shapes,
        "frames": frames,
    }


# ── 化学配平 ──────────────────────────────────────────────────────────────────

_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_SUP = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")


def pretty_formula(formula: str) -> str:
    body, _, charge = formula.partition("^")
    out = re.sub(r"(?<=[A-Za-z\)\]])(\d+)", lambda m: m.group(1).translate(_SUB), body)
    return out + charge.translate(_SUP)


def _chem_timeline(solution: dict[str, Any]) -> dict[str, Any]:
    from oprim.chemical_equation import parse_formula

    reactants: list[str] = list(solution["reactants"])
    products: list[str] = list(solution["products"])
    species = reactants + products
    final = [int(c) for c in solution["coefficients"]]
    parsed = [parse_formula(s) for s in species]
    elements: list[str] = []
    for p in parsed:
        for el in p.counts:
            if el not in elements:
                elements.append(el)
    ionic = any(p.charge for p in parsed)
    rows = elements + (["charge"] if ionic else [])
    nr = len(reactants)

    def totals(coefs: list[int]) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        for row in rows:
            left = right = 0
            for i, p in enumerate(parsed):
                v = p.charge if row == "charge" else p.counts.get(row, 0)
                if i < nr:
                    left += coefs[i] * v
                else:
                    right += coefs[i] * v
            out[row] = (left, right)
        return out

    peak = max(max(abs(v) for v in lr) for lr in totals(final).values())
    peak = max(peak, 1)
    n = len(species)
    width = max(10.0, n * 2.4)
    shapes: list[dict[str, Any]] = []
    base: list[str] = []
    for i, s in enumerate(species):
        x = 1.2 + i * (width - 2.4) / max(n - 1, 1)
        shapes.append(
            {
                "id": f"coef_{i}",
                "type": "text",
                "at": [x - 0.55, 8.6],
                "text": "1",
                "color": "emphasis",
                "size": 22,
                "anchor": "end",
            }
        )
        shapes.append(
            {
                "id": f"sp_{i}",
                "type": "text",
                "at": [x - 0.45, 8.6],
                "text": pretty_formula(s),
                "color": "left" if i < nr else "right",
                "size": 20,
                "anchor": "start",
            }
        )
        base += [f"coef_{i}", f"sp_{i}"]
    shapes.append(
        {
            "id": "arrow_eq",
            "type": "text",
            "at": [width / 2, 9.6],
            "text": "反应物  →  生成物",
            "color": "muted",
            "size": 13,
            "anchor": "middle",
        }
    )
    base.append("arrow_eq")
    row_h = min(1.1, 6.6 / max(len(rows), 1))
    t0 = totals([1] * n)
    for j, row in enumerate(rows):
        y = 6.8 - j * row_h
        label = "电荷" if row == "charge" else row
        shapes.append(
            {
                "id": f"row_{j}",
                "type": "text",
                "at": [width / 2, y],
                "text": label,
                "color": "ink",
                "size": 14,
                "anchor": "middle",
            }
        )
        shapes.append(
            {
                "id": f"barL_{j}",
                "type": "bar",
                "at": [width / 2 - 0.8, y],
                "value": t0[row][0],
                "max": peak,
                "label": str(t0[row][0]),
                "color": "left",
                "width": -(width / 2 - 1.2),
            }
        )
        shapes.append(
            {
                "id": f"barR_{j}",
                "type": "bar",
                "at": [width / 2 + 0.8, y],
                "value": t0[row][1],
                "max": peak,
                "label": str(t0[row][1]),
                "color": "right",
                "width": width / 2 - 1.2,
            }
        )
        base += [f"row_{j}", f"barL_{j}", f"barR_{j}"]

    def sets_for(coefs: list[int]) -> dict[str, dict[str, Any]]:
        tt = totals(coefs)
        out: dict[str, dict[str, Any]] = {
            f"coef_{i}": {"text": "" if c == 1 else str(c)} for i, c in enumerate(coefs)
        }
        for j, row in enumerate(rows):
            left, right = tt[row]
            out[f"barL_{j}"] = {"value": left, "label": str(left)}
            out[f"barR_{j}"] = {"value": right, "label": str(right)}
        return out

    def unbalanced(coefs: list[int]) -> list[str]:
        tt = totals(coefs)
        return [
            f"barL_{j}" for j, row in enumerate(rows) if tt[row][0] != tt[row][1]
        ] + [f"barR_{j}" for j, row in enumerate(rows) if tt[row][0] != tt[row][1]]

    steps = (
        (solution.get("lesson_data") or {}).get("steps") or solution.get("steps") or []
    )
    first_caption = str(steps[0].get("content", "")) if steps else ""
    coefs = [1] * n
    frames = [
        _frame(
            "先全部取 1",
            first_caption or "<p>先把所有计量数设为 1，数一数两边每种原子。</p>",
            show=list(base),
            highlight=unbalanced(coefs),
            set_=sets_for(coefs),
            duration_ms=2600,
        )
    ]
    for i, target in enumerate(final):
        if target == coefs[i]:
            continue
        coefs = coefs[:i] + [target] + coefs[i + 1 :]
        frames.append(
            _frame(
                f"{pretty_formula(species[i])} 的计量数取 {target}",
                f"<p>把 {_esc(pretty_formula(species[i]))} 的计量数设为 <b>{target}</b>，重新数两边的原子{'和电荷' if ionic else ''}。</p>",
                show=list(base),
                highlight=[f"coef_{i}"] + unbalanced(coefs),
                set_=sets_for(coefs),
                duration_ms=1800,
            )
        )
    for step in steps[1:]:
        frames.append(
            _frame(
                str(step.get("title", "")),
                str(step.get("content", "")),
                show=list(base),
                set_=sets_for(final),
                duration_ms=2600,
            )
        )
    frames.append(
        _frame(
            "配平完成",
            f"<p>每一行左右相等，配平完成：${solution['equation_latex']}$</p>",
            show=list(base),
            highlight=[f"coef_{i}" for i in range(n)],
            set_=sets_for(final),
            duration_ms=2600,
        )
    )
    return {
        "kind": "equation_balance",
        "title": solution.get("title", ""),
        "answer": {"label": "配平结果", "latex": solution.get("equation_latex", "")},
        "canvas": {"mode": "2d", "view": [0.0, width, 0.0, 10.4]},
        "shapes": shapes,
        "frames": frames,
    }


# ── 函数图像（visualize 模块内核）─────────────────────────────────────────────


def _zeros(xs: list[float], ys: list[float]) -> list[tuple[float, float]]:
    """采样点上恰为 0 的点 + 相邻异号的线性插值零点（kernel_to_plot2d 的
    _find_zero_crossings 只认严格异号，采样恰落在零点上会漏掉）。"""
    out: list[float] = []
    for i, y in enumerate(ys):
        if y == 0:
            out.append(xs[i])
        elif i + 1 < len(ys) and y * ys[i + 1] < 0:
            out.append(xs[i] - y * (xs[i + 1] - xs[i]) / (ys[i + 1] - y))
    dedup: list[float] = []
    for x in out:
        if not dedup or abs(x - dedup[-1]) > 1e-9:
            dedup.append(x)
    return [(x, 0.0) for x in dedup]


def _function_timeline(params: FunctionGraphParams) -> dict[str, Any]:
    from oprim.kernel_to_plot2d import Plot2DRequest, kernel_to_plot2d

    if params.x_max - params.x_min < 1e-6:
        raise AnimateError("x_max 必须大于 x_min")
    data = kernel_to_plot2d(
        Plot2DRequest(
            expression=params.expression,
            x_range=(params.x_min, params.x_max),
            num_points=241,
        )
    )
    xs, ys = list(data.x_values), list(data.y_values)
    if len(xs) < 2:
        raise AnimateError("表达式无法解析或在该区间没有可画的点")
    srt = sorted(ys)
    lo = srt[int(0.02 * (len(srt) - 1))]
    hi = srt[int(0.98 * (len(srt) - 1))]
    if hi - lo < 1e-6:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.12
    y0, y1 = min(lo - pad, 0.0), max(hi + pad, 0.0)
    x0, x1 = params.x_min, params.x_max
    pts = [[x, max(min(y, y1), y0)] for x, y in zip(xs, ys)]
    shapes: list[dict[str, Any]] = [
        {
            "id": "axis_x",
            "type": "arrow",
            "from": [x0, 0.0],
            "to": [x1, 0.0],
            "color": "axis",
            "label": "x",
        },
    ]
    base = ["axis_x"]
    if x0 <= 0 <= x1:
        shapes.append(
            {
                "id": "axis_y",
                "type": "arrow",
                "from": [0.0, y0],
                "to": [0.0, y1],
                "color": "axis",
                "label": "y",
            }
        )
        base.append("axis_y")
    shapes.append(
        {
            "id": "curve",
            "type": "polyline",
            "pts": pts[:2],
            "color": "curve",
            "width": 2.5,
        }
    )
    zeros = _zeros(xs, ys)[:8]
    zero_ids = []
    for k, (zx, _zy) in enumerate(zeros):
        shapes.append(
            {
                "id": f"zero_{k}",
                "type": "point",
                "at": [zx, 0.0],
                "label": f"{zx:.3g}",
                "color": "emphasis",
            }
        )
        zero_ids.append(f"zero_{k}")
    title = f"y = {params.expression}"
    frames = [
        _frame(
            "坐标系",
            f"<p>在 $x\\in[{x0:g},{x1:g}]$ 上画 $y={_esc(params.expression)}$。</p>",
            show=base + ["curve"],
            set_={"curve": {"pts": pts[:2]}},
            duration_ms=1200,
        )
    ]
    stages = 10
    for s in range(1, stages + 1):
        k = max(2, round(len(pts) * s / stages))
        xe = pts[k - 1][0]
        frames.append(
            _frame(
                f"描点连线 {s}/{stages}",
                f"<p>已画到 $x={xe:.3g}$。</p>",
                show=base + ["curve"],
                set_={"curve": {"pts": pts[:k]}},
                readout=f"x = {xe:.3g}",
                duration_ms=500,
            )
        )
    zero_text = (
        "、".join(f"{zx:.3g}" for zx, _ in zeros)
        if zeros
        else "无（区间内曲线不穿过 x 轴）"
    )
    frames.append(
        _frame(
            "零点",
            f"<p>与 x 轴的交点（零点，数值近似）：{zero_text}</p>",
            show=base + ["curve"] + zero_ids,
            highlight=zero_ids,
            set_={"curve": {"pts": pts}},
            duration_ms=2400,
        )
    )
    return {
        "kind": "function_graph",
        "title": title,
        "answer": {"label": "零点（近似）", "latex": zero_text if zeros else ""},
        "canvas": {"mode": "2d", "view": [x0, x1, y0, y1]},
        "shapes": shapes,
        "frames": frames,
    }


# ── 入口 ──────────────────────────────────────────────────────────────────────


async def build_timeline(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    """kind + params → 确定性时间线。参数不合法/内核无法求解 → AnimateError。"""
    from services.edu_lesson_common import EduKernelError

    try:
        if kind == "solid_geometry":
            from oprim.solid_geometry import SolidGeometrySpec

            from services.solid_geometry_service import (
                SolidGeometryError,
                solve as solid_solve,
            )

            try:
                solution = await solid_solve(SolidGeometrySpec.model_validate(params))
            except SolidGeometryError as exc:
                raise AnimateError(str(exc)) from exc
            return _finish(_solid_timeline(solution))
        if kind == "conic_chord":
            from oprim.conic_analysis import AnalyticGeometrySpec

            from services.conic_geometry_service import solve as conic_solve

            return _finish(
                _conic_timeline(
                    await conic_solve(AnalyticGeometrySpec.model_validate(params))
                )
            )
        if kind == "equation_balance":
            from oprim.chemical_equation import ReactionSpec

            from services.chemical_equation_service import balance

            return _finish(
                _chem_timeline(await balance(ReactionSpec.model_validate(params)))
            )
        if kind == "function_graph":
            fp = FunctionGraphParams.model_validate(params)
            # 与 visualize_service 同样直接调用：kernel_to_plot2d 内部自己 fork 隔离求值
            return _finish(_function_timeline(fp))
    except ValidationError as exc:
        raise AnimateError(
            "参数不合法：" + "; ".join(str(e.get("msg", "")) for e in exc.errors()[:3])
        ) from exc
    except EduKernelError as exc:
        raise AnimateError(str(exc)) from exc
    raise AnimateError(f"unsupported kind: {kind}")
