"""SVG 动画讲解环：AnimatedExplanation 规格、校验门与确定性拼装。

方法来源 wrong-notebook 只学方法、干净重写；本文件不含对方代码。
本环只做规格与拼装：不做 AI 生成（spec 由作者/确定性拼装提供），
不做请求时 TTS 合成（spec 只带 narration_text，前端用 Web Speech
或后续 TTS；音频合成是明确的后续项，见嫁接文档）。

帧词汇直接复用 animate_service（SHAPE_TYPES / SETTABLE），不另造
渲染器。语音同步契约：拼装输出每步的 begin_ms（累计时长），播放器
在上一段旁白读完前不得提前进入下一步（hold 纪律）；旁白超时按
文本长度估算（见嫁接文档），画面不得跑在语音前面。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from services.animate_service import SETTABLE, SHAPE_TYPES

# ── 常量 ───────────────────────────────────────────────────────────────────

#: 步骤数上限（讲解过长则拆成多个规格）。
MAX_STEPS = 20

#: 单步最短/最长旁白时长（ms）；总时长上限 10 分钟。
MIN_STEP_MS = 500
MAX_STEP_MS = 60000
MAX_TOTAL_MS = 600000

#: 帧时长界（ms）。
MIN_FRAME_MS = 200
MAX_FRAME_MS = 30000

#: 帧对象的合法键（animate_service 的帧词汇）。
FRAME_KEYS = frozenset(
    {"title", "caption", "readout", "show", "highlight", "set", "camera", "duration_ms"}
)

#: 语言字段：主语言 + 双语文本对象。
LANGUAGES = ("zh", "en")

#: 溯源标签（复用 provenance.py 的三档口径）。
PROVENANCE_LABELS = ("material", "supplement", "generated")
PROVENANCE_LABEL_ZH = {
    "material": "来自资料",
    "supplement": "AI 补充",
    "generated": "AI 自编答案",
}


# ── 校验门 ────────────────────────────────────────────────────────────────


@dataclass
class AnimationIssue:
    field: str
    code: str
    message: str


@dataclass
class AnimationCheck:
    passed: bool
    issues: list[AnimationIssue] = field(default_factory=list)
    gates: dict[str, bool] = field(default_factory=dict)


def _bilingual(
    value: object, field_name: str, issues: list[AnimationIssue]
) -> Optional[dict[str, str]]:
    if not isinstance(value, dict):
        issues.append(
            AnimationIssue(
                field_name, "not_bilingual", f"{field_name} must be an object with zh and en text"
            )
        )
        return None
    ok = True
    for lang in LANGUAGES:
        text = value.get(lang)
        if not isinstance(text, str) or not text.strip():
            issues.append(
                AnimationIssue(
                    field_name,
                    "missing_language",
                    f"{field_name}.{lang} must be a non-empty string",
                )
            )
            ok = False
    return {lang: value[lang] for lang in LANGUAGES} if ok else None


def _check_provenance(
    spec: Mapping[str, Any], issues: list[AnimationIssue]
) -> None:
    prov = spec.get("provenance")
    if not isinstance(prov, dict):
        issues.append(
            AnimationIssue(
                "provenance", "missing_provenance", "provenance must be an object"
            )
        )
        return
    label = prov.get("label")
    if label not in PROVENANCE_LABELS:
        issues.append(
            AnimationIssue(
                "provenance.label",
                "bad_label",
                f"provenance.label must be one of {', '.join(PROVENANCE_LABELS)}",
            )
        )
        return
    if label == "material":
        sources = prov.get("sources")
        if not isinstance(sources, list) or not sources:
            issues.append(
                AnimationIssue(
                    "provenance.sources",
                    "material_needs_sources",
                    "material provenance requires at least one source",
                )
            )
            return
        for idx, src in enumerate(sources):
            if not isinstance(src, dict) or not isinstance(
                src.get("text"), str
            ) or not src["text"].strip():
                issues.append(
                    AnimationIssue(
                        f"provenance.sources[{idx}]",
                        "bad_source",
                        "each source needs a non-empty text",
                    )
                )


def _check_scene_shapes(
    scene: Mapping[str, Any], field_name: str, issues: list[AnimationIssue]
) -> dict[str, Any]:
    """核验 shape 声明（类型 + 属性白名单）；返回声明表供帧检查用。"""
    shapes = scene.get("shapes")
    if not isinstance(shapes, dict) or not shapes:
        issues.append(
            AnimationIssue(
                f"{field_name}.shapes",
                "empty_shapes",
                "scene.shapes must be a non-empty object",
            )
        )
        return {}
    for shape_id, shape in shapes.items():
        sfield = f"{field_name}.shapes.{shape_id}"
        if not isinstance(shape, dict):
            issues.append(
                AnimationIssue(sfield, "not_an_object", "shape must be an object")
            )
            continue
        shape_type = shape.get("type")
        allowed = SHAPE_TYPES.get(shape_type) if isinstance(shape_type, str) else None
        if allowed is None:
            issues.append(
                AnimationIssue(
                    f"{sfield}.type",
                    "bad_shape_type",
                    f"unknown shape type {shape_type!r}",
                )
            )
            continue
        for attr in shape:
            if attr != "type" and attr not in allowed:
                issues.append(
                    AnimationIssue(
                        f"{sfield}.{attr}",
                        "bad_shape_attr",
                        f"attribute {attr!r} is not allowed for shape type {shape_type!r}",
                    )
                )
    return shapes


def _check_scene_frames(
    scene: Mapping[str, Any],
    shapes: Mapping[str, Any],
    field_name: str,
    issues: list[AnimationIssue],
) -> None:
    """核验帧：键词汇 + show/highlight/set 引用闭合 + settable + 帧时长。"""
    frames = scene.get("frames")
    if not isinstance(frames, list) or not frames:
        issues.append(
            AnimationIssue(
                f"{field_name}.frames",
                "empty_frames",
                "scene.frames must be a non-empty list",
            )
        )
        return
    for fidx, frame in enumerate(frames):
        ffield = f"{field_name}.frames[{fidx}]"
        if not isinstance(frame, dict):
            issues.append(
                AnimationIssue(ffield, "not_an_object", "frame must be an object")
            )
            continue
        for key in frame:
            if key not in FRAME_KEYS:
                issues.append(
                    AnimationIssue(
                        f"{ffield}.{key}",
                        "bad_frame_key",
                        f"frame key {key!r} is outside the animate_service vocabulary",
                    )
                )
        for list_key in ("show", "highlight"):
            shown = frame.get(list_key)
            if shown is None:
                continue
            if not isinstance(shown, list) or not all(
                isinstance(s, str) for s in shown
            ):
                issues.append(
                    AnimationIssue(
                        f"{ffield}.{list_key}",
                        "bad_reference_list",
                        f"{list_key} must be a list of shape ids",
                    )
                )
                continue
            for shape_id in shown:
                if shape_id not in shapes:
                    issues.append(
                        AnimationIssue(
                            f"{ffield}.{list_key}",
                            "undeclared_shape",
                            f"shape {shape_id!r} is not declared in scene.shapes",
                        )
                    )
        setters = frame.get("set")
        if setters is not None:
            if not isinstance(setters, dict):
                issues.append(
                    AnimationIssue(
                        f"{ffield}.set", "not_an_object", "set must be an object"
                    )
                )
            else:
                for shape_id, attrs in setters.items():
                    if shape_id not in shapes:
                        issues.append(
                            AnimationIssue(
                                f"{ffield}.set",
                                "undeclared_shape",
                                f"shape {shape_id!r} is not declared in scene.shapes",
                            )
                        )
                        continue
                    if not isinstance(attrs, dict):
                        issues.append(
                            AnimationIssue(
                                f"{ffield}.set.{shape_id}",
                                "not_an_object",
                                "set value must be an object of attributes",
                            )
                        )
                        continue
                    for attr in attrs:
                        if attr not in SETTABLE:
                            issues.append(
                                AnimationIssue(
                                    f"{ffield}.set.{shape_id}.{attr}",
                                    "not_settable",
                                    f"attribute {attr!r} is not settable",
                                )
                            )
        duration = frame.get("duration_ms")
        if duration is not None and (
            not isinstance(duration, int)
            or isinstance(duration, bool)
            or not MIN_FRAME_MS <= duration <= MAX_FRAME_MS
        ):
            issues.append(
                AnimationIssue(
                    f"{ffield}.duration_ms",
                    "frame_duration_out_of_range",
                    f"duration_ms must be an int in [{MIN_FRAME_MS}, {MAX_FRAME_MS}]",
                )
            )


def verify_animation(
    spec: object,
    known_question_ids: Optional[set[str]] = None,
    known_ku_ids: Optional[set[str]] = None,
) -> AnimationCheck:
    """验证门：10 项全过才 verified，失败逐条列原因。

    g1 schema；g2 语言字段；g3 步骤结构；g4 旁白文本；g5 场景 shape
    声明闭合；g6 帧词汇与帧时长；g7 溯源齐全；g8 引用存在（fail-closed：
    不传核验集即不通过）；g9 时长有界；g10 verified 字段禁带。
    """
    issues: list[AnimationIssue] = []
    gates: dict[str, bool] = {}

    def _gate(name: str, before: int) -> None:
        gates[name] = len(issues) == before

    # g1：schema 合法、id 齐全、steps 为列表。
    mark = len(issues)
    if not isinstance(spec, dict):
        issues.append(
            AnimationIssue("", "not_an_object", "spec must be an object")
        )
        _gate("g1", mark)
        return AnimationCheck(passed=False, issues=issues, gates=gates)
    spec_id = spec.get("id")
    if not isinstance(spec_id, str) or not spec_id.strip():
        issues.append(
            AnimationIssue("id", "missing_id", "id must be a non-empty string")
        )
    steps = spec.get("steps")
    if not isinstance(steps, list):
        issues.append(
            AnimationIssue("steps", "not_a_list", "steps must be a list")
        )
        steps = []
    _gate("g1", mark)

    # g2：语言字段齐全（主语言 + 双语标题）。
    mark = len(issues)
    language = spec.get("language")
    if language not in LANGUAGES:
        issues.append(
            AnimationIssue(
                "language",
                "bad_language",
                f"language must be one of {', '.join(LANGUAGES)}",
            )
        )
    _bilingual(spec.get("title"), "title", issues)
    _gate("g2", mark)

    # g3：步骤结构（1..MAX_STEPS，每步含 scene/narration/min_duration）。
    mark = len(issues)
    if isinstance(spec.get("steps"), list):
        if not 1 <= len(steps) <= MAX_STEPS:
            issues.append(
                AnimationIssue(
                    "steps",
                    "bad_step_count",
                    f"steps must contain 1..{MAX_STEPS} steps",
                )
            )
        for idx, step in enumerate(steps):
            sfield = f"steps[{idx}]"
            if not isinstance(step, dict):
                issues.append(
                    AnimationIssue(sfield, "not_an_object", "step must be an object")
                )
                continue
            for key in ("scene", "narration_text", "min_duration_ms"):
                if key not in step:
                    issues.append(
                        AnimationIssue(
                            sfield, "missing_field", f"step is missing {key!r}"
                        )
                    )
    _gate("g3", mark)

    # g4：旁白文本双语非空。
    mark = len(issues)
    for idx, step in enumerate(steps):
        if isinstance(step, dict) and "narration_text" in step:
            _bilingual(step["narration_text"], f"steps[{idx}].narration_text", issues)
    _gate("g4", mark)

    # g5：场景 shape 声明闭合（类型 + 属性白名单）。
    mark = len(issues)
    declared: list[dict[str, Any]] = []
    for idx, step in enumerate(steps):
        if isinstance(step, dict) and "scene" in step:
            scene = step["scene"]
            if isinstance(scene, dict):
                declared.append(
                    _check_scene_shapes(scene, f"steps[{idx}].scene", issues)
                )
            else:
                issues.append(
                    AnimationIssue(
                        f"steps[{idx}].scene",
                        "not_an_object",
                        "scene must be an object",
                    )
                )
                declared.append({})
        else:
            declared.append({})
    _gate("g5", mark)

    # g6：帧词汇与帧时长（show/highlight/set 引用闭合 + settable + 时长界）。
    mark = len(issues)
    for idx, step in enumerate(steps):
        if isinstance(step, dict) and "scene" in step:
            scene = step["scene"]
            if isinstance(scene, dict):
                _check_scene_frames(
                    scene, declared[idx], f"steps[{idx}].scene", issues
                )
    _gate("g6", mark)

    # g7：溯源齐全。
    mark = len(issues)
    _check_provenance(spec, issues)
    _gate("g7", mark)

    # g8：引用存在（fail-closed）。
    mark = len(issues)
    question_id = spec.get("question_id")
    if question_id is not None:
        if not isinstance(question_id, str) or not question_id.strip():
            issues.append(
                AnimationIssue(
                    "question_id",
                    "bad_question_id",
                    "question_id must be a non-empty string",
                )
            )
        elif known_question_ids is None or question_id not in known_question_ids:
            issues.append(
                AnimationIssue(
                    "question_id",
                    "question_not_found",
                    f"question {question_id!r} does not exist",
                )
            )
    ku_id = spec.get("ku_id")
    if ku_id is not None:
        if not isinstance(ku_id, str) or not ku_id.strip():
            issues.append(
                AnimationIssue(
                    "ku_id", "bad_ku_id", "ku_id must be a non-empty string"
                )
            )
        elif known_ku_ids is None or ku_id not in known_ku_ids:
            issues.append(
                AnimationIssue(
                    "ku_id", "ku_not_found", f"ku {ku_id!r} does not exist"
                )
            )
    _gate("g8", mark)

    # g9：时长有界（单步 + 总计）。
    mark = len(issues)
    total = 0
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        duration = step.get("min_duration_ms")
        if duration is None:
            continue
        if (
            not isinstance(duration, int)
            or isinstance(duration, bool)
            or not MIN_STEP_MS <= duration <= MAX_STEP_MS
        ):
            issues.append(
                AnimationIssue(
                    f"steps[{idx}].min_duration_ms",
                    "step_duration_out_of_range",
                    f"min_duration_ms must be an int in [{MIN_STEP_MS}, {MAX_STEP_MS}]",
                )
            )
        else:
            total += duration
    if total > MAX_TOTAL_MS:
        issues.append(
            AnimationIssue(
                "steps",
                "total_duration_too_long",
                f"total min duration exceeds {MAX_TOTAL_MS} ms",
            )
        )
    _gate("g9", mark)

    # g10：verified 字段只由服务端门禁设置，规格内禁止携带。
    mark = len(issues)
    if "verified" in spec:
        issues.append(
            AnimationIssue(
                "verified",
                "verified_field_forbidden",
                "verified is set by the server-side gate only",
            )
        )
    _gate("g10", mark)

    return AnimationCheck(passed=not issues, issues=issues, gates=gates)


def animation_provenance(spec: Mapping[str, Any]) -> dict[str, Any]:
    """规格携带的溯源标签（复用 provenance.py 的三档口径）。"""
    prov = spec.get("provenance") if isinstance(spec, dict) else None
    label = prov.get("label") if isinstance(prov, dict) else None
    sources = prov.get("sources") if isinstance(prov, dict) else None
    return {
        "label": label if label in PROVENANCE_LABELS else "generated",
        "label_text": PROVENANCE_LABEL_ZH.get(label, PROVENANCE_LABEL_ZH["generated"]),
        "sources": sources if isinstance(sources, list) else [],
    }


# ── 拼装 ───────────────────────────────────────────────────────────────────


class AnimationAssemblyError(ValueError):
    """拼装输入结构损坏（只应在未过门禁的规格上触发）。"""


def assemble_animation(spec: Mapping[str, Any]) -> dict[str, Any]:
    """确定性拼装：steps + 每步 frames + 旁白时间线（begin_ms 累计）。

    假设 spec 已过 verify_animation；结构损坏时抛 AnimationAssemblyError。
    帧直接沿用 animate_service 的帧结构，不另造渲染器。
    """
    if not isinstance(spec, dict):
        raise AnimationAssemblyError("spec must be an object")
    steps = spec.get("steps")
    if not isinstance(steps, list) or not steps:
        raise AnimationAssemblyError("steps must be a non-empty list")
    out_steps: list[dict[str, Any]] = []
    begin_ms = 0
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise AnimationAssemblyError(f"steps[{index}] must be an object")
        scene = step.get("scene")
        narration = step.get("narration_text")
        duration = step.get("min_duration_ms")
        if (
            not isinstance(scene, dict)
            or not isinstance(narration, dict)
            or not isinstance(duration, int)
        ):
            raise AnimationAssemblyError(f"steps[{index}] is malformed")
        out_steps.append(
            {
                "index": index,
                "begin_ms": begin_ms,
                "min_duration_ms": duration,
                "narration": narration,
                "frames": scene.get("frames", []),
                "shapes": scene.get("shapes", {}),
            }
        )
        begin_ms += duration
    return {
        "id": spec.get("id"),
        "title": spec.get("title"),
        "language": spec.get("language"),
        "question_id": spec.get("question_id"),
        "ku_id": spec.get("ku_id"),
        "steps": out_steps,
        "total_duration_ms": begin_ms,
        "provenance": animation_provenance(spec),
    }


# ── 自写参照动画（取自 Mneme 自有 K12 数学内容） ─────────────────────────


def linear_shift_spec(spec_id: str = "anim-linear-shift") -> dict[str, Any]:
    """一次函数图像平移：y = x + 1 向上平移 2 个单位得 y = x + 3。

    期望：首帧只见坐标轴与原直线；第二步高亮原直线并出现平移后的
    直线；第三步两直线同屏，截距 +2、斜率不变。
    """
    axes = {"type": "segment", "from": [0, 5], "to": [10, 5], "color": "axis"}
    axis_y = {"type": "segment", "from": [5, 0], "to": [5, 10], "color": "axis"}
    line1 = {
        "type": "polyline",
        "pts": [[1, 7], [9, 15]],
        "color": "curve",
        "width": 2,
    }
    line2 = {
        "type": "polyline",
        "pts": [[1, 9], [9, 17]],
        "color": "line",
        "width": 2,
        "dashed": True,
    }
    label1 = {"type": "text", "at": [8, 15], "text": "y = x + 1", "color": "curve"}
    label2 = {"type": "text", "at": [8, 17], "text": "y = x + 3", "color": "line"}
    shapes = {
        "axes": axes,
        "axis_y": axis_y,
        "line1": line1,
        "line2": line2,
        "label1": label1,
        "label2": label2,
    }
    return {
        "id": spec_id,
        "language": "zh",
        "title": {"zh": "一次函数图像平移", "en": "Translating a linear graph"},
        "provenance": {"label": "generated", "sources": []},
        "steps": [
            {
                "scene": {
                    "shapes": shapes,
                    "frames": [
                        {
                            "title": {"zh": "原直线", "en": "Original line"},
                            "show": ["axes", "axis_y", "line1", "label1"],
                            "duration_ms": 2000,
                        }
                    ],
                },
                "narration_text": {
                    "zh": "这是直线 y 等于 x 加 1，斜率是 1，截距是 1。",
                    "en": "This is the line y equals x plus 1, with slope 1 and intercept 1.",
                },
                "min_duration_ms": 3000,
            },
            {
                "scene": {
                    "shapes": shapes,
                    "frames": [
                        {
                            "title": {"zh": "向上平移", "en": "Shift up"},
                            "show": ["axes", "axis_y", "line1", "line2"],
                            "highlight": ["line1"],
                            "duration_ms": 2500,
                        }
                    ],
                },
                "narration_text": {
                    "zh": "把图像向上平移 2 个单位，得到虚线所示的新直线。",
                    "en": "Shift the graph up by 2 units to get the dashed new line.",
                },
                "min_duration_ms": 3500,
            },
            {
                "scene": {
                    "shapes": shapes,
                    "frames": [
                        {
                            "title": {"zh": "对比结论", "en": "Compare"},
                            "show": ["axes", "axis_y", "line1", "line2", "label1", "label2"],
                            "highlight": ["label2"],
                            "duration_ms": 2500,
                        }
                    ],
                },
                "narration_text": {
                    "zh": "新直线是 y 等于 x 加 3：截距加 2，斜率不变。",
                    "en": "The new line is y equals x plus 3: the intercept grows by 2, the slope stays.",
                },
                "min_duration_ms": 3500,
            },
        ],
    }


def pythagorean_spec(spec_id: str = "anim-pythagorean") -> dict[str, Any]:
    """勾股数验证：3-4-5 直角三角形，两直角边上正方形面积和等于斜边上正方形面积。

    期望：首帧只见直角三角形；第二步出现三边上的正方形；第三步
    高亮面积标注，9 加 16 等于 25。
    """
    triangle = {
        "type": "polygon",
        "pts": [[1, 1], [5, 1], [1, 4]],
        "color": "curve",
        "opacity": 0.9,
    }
    sq_a = {
        "type": "polygon",
        "pts": [[1, 1], [5, 1], [5, -3], [1, -3]],
        "color": "line",
        "opacity": 0.5,
    }
    sq_b = {
        "type": "polygon",
        "pts": [[1, 1], [1, 4], [-2, 4], [-2, 1]],
        "color": "line",
        "opacity": 0.5,
    }
    sq_c = {
        "type": "polygon",
        "pts": [[5, 1], [1, 4], [-2, 8], [2, 5]],
        "color": "curve",
        "opacity": 0.5,
    }
    label_a = {"type": "text", "at": [3, -1], "text": "3² = 9", "color": "ink"}
    label_b = {"type": "text", "at": [-1, 2], "text": "4² = 16", "color": "ink"}
    label_c = {"type": "text", "at": [0, 6], "text": "5² = 25", "color": "ink"}
    shapes = {
        "triangle": triangle,
        "sq_a": sq_a,
        "sq_b": sq_b,
        "sq_c": sq_c,
        "label_a": label_a,
        "label_b": label_b,
        "label_c": label_c,
    }
    return {
        "id": spec_id,
        "language": "zh",
        "title": {"zh": "勾股数验证：3-4-5", "en": "Checking 3-4-5 with Pythagoras"},
        "provenance": {"label": "generated", "sources": []},
        "steps": [
            {
                "scene": {
                    "shapes": shapes,
                    "frames": [
                        {
                            "title": {"zh": "直角三角形", "en": "Right triangle"},
                            "show": ["triangle"],
                            "duration_ms": 2000,
                        }
                    ],
                },
                "narration_text": {
                    "zh": "一个直角三角形，两条直角边分别是 3 和 4，斜边是 5。",
                    "en": "A right triangle with legs 3 and 4 and hypotenuse 5.",
                },
                "min_duration_ms": 3000,
            },
            {
                "scene": {
                    "shapes": shapes,
                    "frames": [
                        {
                            "title": {"zh": "三边上的正方形", "en": "Squares on the sides"},
                            "show": ["triangle", "sq_a", "sq_b", "sq_c"],
                            "duration_ms": 2500,
                        }
                    ],
                },
                "narration_text": {
                    "zh": "在三条边上各作一个正方形，它们的面积分别是 9、16 和 25。",
                    "en": "Build a square on each side: their areas are 9, 16 and 25.",
                },
                "min_duration_ms": 3500,
            },
            {
                "scene": {
                    "shapes": shapes,
                    "frames": [
                        {
                            "title": {"zh": "面积相加", "en": "Add the areas"},
                            "show": ["triangle", "sq_a", "sq_b", "sq_c", "label_a", "label_b", "label_c"],
                            "highlight": ["label_c"],
                            "duration_ms": 2500,
                        }
                    ],
                },
                "narration_text": {
                    "zh": "9 加 16 等于 25，正好等于斜边上正方形的面积。",
                    "en": "9 plus 16 equals 25, exactly the area of the square on the hypotenuse.",
                },
                "min_duration_ms": 3500,
            },
        ],
    }


__all__ = [
    "AnimationAssemblyError",
    "AnimationCheck",
    "AnimationIssue",
    "FRAME_KEYS",
    "LANGUAGES",
    "MAX_STEPS",
    "MAX_TOTAL_MS",
    "assemble_animation",
    "animation_provenance",
    "linear_shift_spec",
    "pythagorean_spec",
    "verify_animation",
]
