"""交互式 3D 教学页规格合同 + 页级校验门（G1）+ 渲染识别契约（G2）+ 交互控件契约（G3）。

方法来源：andyhuo520/aetherviz-master（MIT，Copyright (c) 2026 andyhu）。
干净重写：只学方法，不搬对方 SKILL.md / README 的原文、代码、演示图，
不搬分支 web/ 的代码与 GSAP；关键词表是复核后的方法输入，学科归属
按 Mneme 自家复核纠正（README 把“光合作用”误列在化学名下，本模块
归生物）；数值口径（配色档、版本钉死）以复核结论为准。

本模块是纯函数，无 DB、无网络、无 LLM 调用，可脱服务直测。
它补的是 viz_generator 已有链路缺的那一环：viz_generator
（services/viz_generator.py，主仓已有，hark/aetherviz 线）做生成后
质检（quality_check：可解析、白名单库、无外部主机、KaTeX、测验），
本模块做生成前规格门禁——页长什么样、控件有哪些、依赖走哪条
 profile、断言有没有出处。两者互补，不互相替代。

与已接门禁的关系（图级 vs 页级）：
- teachable-figures（services/teaching_figure.py）管“图对不对”：
  spec 带 figures 时，每张图都要过 verify_figure，否则本门禁 g5 不过。
- Atlas of Physics（services/physics_models.py）管物理场景语义：
  subject 为 physics 时，本模块不另起一套物理场景规范，只要求
  atlas_model_ref 指到 Atlas 注册模型名；矢量配色等场景细节以
  Atlas 模型为准，本模块只验相机/灯光/渲染器基线。
- 出处（g9/g10）fail-closed：断言须过 citation_check；source_ledger
  须过 vibe-knowledge G1 台账门禁——但台账模块
  （services/narration_source_ledger.py）目前只在未合并分支
  feat/narration-source-ledger-g1 上，主仓没有。本模块不 import 它，
  改由调用方注入 ledger_check（签名见 verify_interactive_page）；
  未注入时 g10 直接判 ledger_gate_unavailable，不放行。合并顺序：
  台账分支合入 main 后，路由层把 verify_lesson_source_ledger
  作为 ledger_check 传进来即可，本模块不用改。

依赖 profile（上游 CDN 口径与 Mneme 自托管口径的冲突已实查）：
- 上游钉死 CDN：Three.js r134、Tailwind v3.4+、KaTeX 0.16.11、
  D3.js v7（可选），且“零依赖外部文件”自相矛盾——实为全走 CDN，
  离线不可用、无 SRI 校验。
- Mneme 生产口径（viz_generator.LIBS）：自托管 /v1/edu-assets/，
  Three.js 0.134.0、KaTeX 0.16.8、D3 7.9.0，不用 Tailwind CDN。
  KaTeX 版本漂移（上游 0.16.11 vs 仓内 0.16.8）已记录在嫁接报告，
  未擅自统一。
- 本门禁接受两种 profile（二选一，不混用）：
  self_hosted（首选，须与 viz_generator.LIBS 一致）、cdn_pinned
  （上游口径：版本钉死 + 每条须带 integrity，否则 missing_sri
  不过；requires_network 须为 True，offline_available 须为 False）。

确定性裁决（Soffy 2026-11-20 点选时已定）：随机实验默认关；
开时必须带固定 seed，否则 random_requires_seed 不过。

未进门禁、如实记缺口：60fps（上游自称，无测试无实测，本模块
不背书）；生成 HTML 的实际渲染质量（本模块只验规格，不跑渲染）。
"""

from __future__ import annotations

import re
from typing import Any, Callable, Collection, Mapping, Optional

from services.citation_check import check_citations
from services.provenance import ProvenanceLabel
from services.teaching_figure import verify_figure

__all__ = [
    "ALLOWED_SPEEDS",
    "CDN_PINNED",
    "CONTROL_KINDS",
    "CONTROL_STATES",
    "CONTROL_TRANSITIONS",
    "LAYOUT",
    "PageCheck",
    "PageIssue",
    "RENDER_MODES",
    "REQUIRED_CONTROLS",
    "SELF_HOSTED_LIBS",
    "SUBJECTS",
    "SUBJECT_PALETTES",
    "VECTOR_COLORS",
    "control_checklist",
    "detect_render_mode",
    "detect_subject",
    "example_spec",
    "transition",
    "validate_controls",
    "verify_interactive_page",
]

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# ── G1：页面结构与学科（干净重写后的 Mneme 口径）────────────────────────

#: 布局钉死值：侧栏 30% / 主画布 70%（分支提示词的 25%/75% 是漂移，不过）。
LAYOUT = {
    "sidebar_ratio": 0.30,
    "canvas_ratio": 0.70,
    "quiz_width_px": 360,
    "quiz_max_height_px": 380,
    "quiz_transition_s": 0.3,
}

SUBJECTS = ("physics", "chemistry", "biology", "math", "astronomy", "programming")

#: 学科配色只取档位名，不搬上游渐变 CSS（G6 设计系统不追）。
SUBJECT_PALETTES = {
    "physics": "blue",
    "chemistry": "orange-red",
    "biology": "green",
    "math": "gold",
    "astronomy": "deep-blue",
    "programming": "teal",
}

#: 学科识别关键词（Mneme 自家复核顺序：天文/生物/化学/数学/编程/物理）。
#: “光合作用”归生物（上游 README 误列化学，已纠正）；“分子结构”归化学。
SUBJECT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "astronomy": ("行星", "宇宙", "黑洞", "日食", "月食", "天体", "恒星"),
    "biology": ("光合作用", "细胞", "DNA", "遗传", "有丝分裂", "呼吸", "基因", "生态"),
    "chemistry": ("酸碱", "氧化", "还原", "中和", "分子结构", "化学反应", "元素"),
    "math": ("函数", "定理", "概率", "统计", "几何", "勾股", "三角", "方程", "微积分"),
    "programming": ("算法", "数据结构", "排序", "设计模式", "编程", "代码", "递归"),
    "physics": (
        "牛顿", "运动", "力", "电磁", "磁场", "电场", "粒子",
        "碰撞", "旋转", "机械", "波动", "振动", "相对论", "量子", "能量",
    ),
}
_SUBJECT_ORDER = ("astronomy", "biology", "chemistry", "math", "programming", "physics")

# ── G2：渲染模式识别（复核后的方法输入；计数与上游一致）────────────────

RENDER_MODES = ("three", "svg", "hybrid")
THREE_KEYWORDS = ("运动", "粒子", "碰撞", "旋转", "天体", "分子", "机械", "力", "磁场", "电场")
SVG_KEYWORDS = ("函数", "图像", "曲线", "图表", "统计", "证明", "几何", "坐标")
HYBRID_KEYWORDS = ("牛顿", "运动定律", "波动", "振动", "电磁", "能量")


def detect_render_mode(topic: str) -> str:
    """按关键词判定渲染模式：hybrid 优先（有 hybrid 词，或 three+svg 同时命中）。

    无关键词命中时默认 three。空主题抛 ValueError（调用方 fail-closed）。
    注意：该规则复现不了上游示例表的全部归类——“勾股定理”“概率分布”
    在示例表里属 SVG，但按规则得 three；规格可用 render_mode_override_reason
    书面说明后覆盖默认值，见 verify_interactive_page 的 g4。
    """
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("topic must be a non-empty string")
    has_three = any(k in topic for k in THREE_KEYWORDS)
    has_svg = any(k in topic for k in SVG_KEYWORDS)
    has_hybrid = any(k in topic for k in HYBRID_KEYWORDS)
    if has_hybrid or (has_three and has_svg):
        return "hybrid"
    if has_svg:
        return "svg"
    return "three"


def detect_subject(topic: str) -> Optional[str]:
    """按关键词判定学科；无命中返回 None（不猜）。"""
    if not isinstance(topic, str) or not topic.strip():
        return None
    for subject in _SUBJECT_ORDER:
        if any(k in topic for k in SUBJECT_KEYWORDS[subject]):
            return subject
    return None


# ── G1：Three.js 场景基线与依赖 profile ───────────────────────────────────

#: 矢量配色约定（复核后的方法输入；物理学科以 Atlas 模型为准，此处只用于非物理学科）。
VECTOR_COLORS = {
    "force": "#EF4444",
    "velocity": "#3B82F6",
    "acceleration": "#22C55E",
}

#: 上游 CDN 钉死版本（参考口径；Mneme 生产首选 self_hosted）。
CDN_PINNED = {
    "three": "r134",
    "tailwind": "v3.4+",
    "katex": "0.16.11",
    "d3": "v7",
}
ALLOWED_CDN_HOSTS = ("cdnjs.cloudflare.com", "cdn.jsdelivr.net", "cdn.tailwindcss.com", "d3js.org")

#: Mneme 自托管口径，与 viz_generator.LIBS 一致（KaTeX 0.16.8，注意与上游 0.16.11 的漂移）。
SELF_HOSTED_LIBS = {
    "three": {"version": "0.134.0", "url": "/v1/edu-assets/three-0.134.0/three.min.js"},
    "orbit": {"version": "0.134.0", "url": "/v1/edu-assets/three-0.134.0/OrbitControls.js"},
    "katex_css": {"version": "0.16.8", "url": "/v1/edu-assets/katex-0.16.8/katex.min.css"},
    "katex_js": {"version": "0.16.8", "url": "/v1/edu-assets/katex-0.16.8/katex.min.js"},
    "katex_auto": {"version": "0.16.8", "url": "/v1/edu-assets/katex-0.16.8/contrib/auto-render.min.js"},
    "d3": {"version": "7.9.0", "url": "/v1/edu-assets/d3-7.9.0/d3.min.js"},
}


# ── G3：交互控件契约 ─────────────────────────────────────────────────────

CONTROL_KINDS = (
    "slider", "play", "pause", "step", "speed", "reset",
    "random_experiment", "objectives_checklist", "click_highlight",
)
#: random_experiment 之外全部必备；随机实验默认关（见模块 docstring 的确定性裁决）。
REQUIRED_CONTROLS = tuple(k for k in CONTROL_KINDS if k != "random_experiment")
ALLOWED_SPEEDS = (0.25, 0.5, 1.0, 2.0, 4.0)

CONTROL_STATES = ("idle", "playing", "paused")
#: 状态机：单步只许在 paused 下；播放/暂停/重置的非法转移直接拒。
CONTROL_TRANSITIONS: dict[str, dict[str, str]] = {
    "idle": {"play": "playing", "reset": "idle"},
    "playing": {"pause": "paused", "reset": "idle"},
    "paused": {"play": "playing", "step": "paused", "reset": "idle"},
}


def transition(state: str, action: str) -> str:
    """控件状态机的一步转移；speed 只改倍率不改状态；非法转移抛 ValueError。"""
    if action == "speed":
        if state not in CONTROL_STATES:
            raise ValueError(f"unknown control state: {state!r}")
        return state
    allowed = CONTROL_TRANSITIONS.get(state)
    if allowed is None:
        raise ValueError(f"unknown control state: {state!r}")
    if action not in allowed:
        raise ValueError(f"illegal control transition: {state!r} --{action}--> ?")
    return allowed[action]


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class PageIssue:
    def __init__(self, field: str, code: str, message: str) -> None:
        self.field = field
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "message": self.message}


class PageCheck:
    def __init__(self, gates: dict[str, bool], issues: list[PageIssue]) -> None:
        self.gates = gates
        self.issues = issues

    @property
    def passed(self) -> bool:
        return all(self.gates.values()) and not self.issues


def _check_slider(control: Mapping[str, Any], issues: list[PageIssue], field: str) -> None:
    low, high, step, value = (control.get(k) for k in ("min", "max", "step", "value"))
    if not all(_is_number(v) for v in (low, high, step, value)):
        issues.append(PageIssue(field, "bad_slider_bounds", "slider min/max/step/value must be numbers"))
        return
    if not low < high:  # type: ignore[operator]
        issues.append(PageIssue(field, "bad_slider_bounds", "slider min must be less than max"))
    if not step > 0:  # type: ignore[operator]
        issues.append(PageIssue(field, "bad_slider_step", "slider step must be positive"))
    if not low <= value <= high:  # type: ignore[operator]
        issues.append(PageIssue(field, "bad_slider_value", "slider value must lie within [min, max]"))


def _check_speed(control: Mapping[str, Any], issues: list[PageIssue], field: str) -> None:
    options = control.get("options")
    value = control.get("value")
    if not isinstance(options, list) or not options or not all(
        _is_number(o) and o in ALLOWED_SPEEDS for o in options
    ):
        issues.append(
            PageIssue(field, "bad_speed_options", f"speed options must be a non-empty subset of {ALLOWED_SPEEDS}")
        )
        return
    if not _is_number(value) or value not in options:
        issues.append(PageIssue(field, "bad_speed_value", "speed value must be one of its options"))


def _check_random(control: Mapping[str, Any], issues: list[PageIssue], field: str) -> None:
    if control.get("enabled") is True and not _is_int(control.get("seed")):
        issues.append(
            PageIssue(field, "random_requires_seed", "random_experiment enabled requires a fixed integer seed")
        )


def _check_objectives(control: Mapping[str, Any], issues: list[PageIssue], field: str) -> None:
    items = control.get("items")
    if (
        not isinstance(items, list)
        or not 3 <= len(items) <= 4
        or not all(isinstance(i, str) and i.strip() for i in items)
    ):
        issues.append(
            PageIssue(field, "bad_objectives", "objectives_checklist needs 3 to 4 non-empty items")
        )


def validate_controls(controls: object) -> list[PageIssue]:
    """校验控件清单：必备齐全且启用、种类内参数合法、随机实验默认关。"""
    issues: list[PageIssue] = []
    if not isinstance(controls, list) or not controls:
        return [PageIssue("controls", "missing_controls", "controls must be a non-empty list")]
    seen: dict[str, Mapping[str, Any]] = {}
    for pos, control in enumerate(controls):
        field = f"controls[{pos}]"
        if not isinstance(control, dict):
            issues.append(PageIssue(field, "not_an_object", "control must be an object"))
            continue
        kind = control.get("kind")
        if kind not in CONTROL_KINDS:
            issues.append(PageIssue(field, "bad_control_kind", f"control kind must be one of {CONTROL_KINDS}"))
            continue
        if kind in seen:
            issues.append(PageIssue(f"{field}.kind", "duplicate_control", f"duplicate control kind: {kind}"))
            continue
        seen[kind] = control
        if kind != "random_experiment" and control.get("enabled") is not True:
            issues.append(PageIssue(field, "control_disabled", f"required control {kind!r} must be enabled"))
        if kind == "slider":
            _check_slider(control, issues, field)
        elif kind == "speed":
            _check_speed(control, issues, field)
        elif kind == "random_experiment":
            _check_random(control, issues, field)
        elif kind == "objectives_checklist":
            _check_objectives(control, issues, field)
    for kind in REQUIRED_CONTROLS:
        if kind not in seen:
            issues.append(PageIssue("controls", "missing_control", f"missing required control: {kind}"))
    return issues


def control_checklist(controls: object) -> list[dict[str, Any]]:
    """控件验收清单：每行 {control, required, present, enabled, status, note}。"""
    by_kind: dict[str, Mapping[str, Any]] = {}
    if isinstance(controls, list):
        for control in controls:
            if isinstance(control, dict) and control.get("kind") in CONTROL_KINDS:
                by_kind.setdefault(str(control["kind"]), control)
    rows: list[dict[str, Any]] = []
    for kind in CONTROL_KINDS:
        present = kind in by_kind
        enabled = bool(present and by_kind[kind].get("enabled") is True)
        required = kind in REQUIRED_CONTROLS
        if kind == "random_experiment":
            note = "default off; enabling requires a fixed seed"
            status = "pass" if (not present or not enabled or _is_int(by_kind[kind].get("seed"))) else "fail"
        else:
            note = "required" if required else ""
            status = "pass" if present and enabled else "fail"
        rows.append(
            {
                "control": kind,
                "required": required,
                "present": present,
                "enabled": enabled,
                "status": status,
                "note": note,
            }
        )
    return rows


# ── G1：页级校验门 verify_interactive_page（g1–g10，全过才通过）─────────


def _bilingual(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("zh"), str)
        and value["zh"].strip() != ""
        and isinstance(value.get("en"), str)
        and value["en"].strip() != ""
    )


def _close(a: float, b: float) -> bool:
    return abs(a - b) < 1e-9


def _check_layout(spec: Mapping[str, Any], issues: list[PageIssue]) -> bool:
    layout = spec.get("layout")
    if not isinstance(layout, dict):
        issues.append(PageIssue("layout", "missing_layout", "layout must be an object"))
        return False
    ok = True
    if not _is_number(layout.get("sidebar_ratio")) or not _close(
        float(layout["sidebar_ratio"]), LAYOUT["sidebar_ratio"]  # type: ignore[arg-type]
    ):
        issues.append(PageIssue("layout.sidebar_ratio", "bad_sidebar_ratio", "sidebar_ratio must be 0.30"))
        ok = False
    if not _is_number(layout.get("canvas_ratio")) or not _close(
        float(layout["canvas_ratio"]), LAYOUT["canvas_ratio"]  # type: ignore[arg-type]
    ):
        issues.append(PageIssue("layout.canvas_ratio", "bad_canvas_ratio", "canvas_ratio must be 0.70"))
        ok = False
    if layout.get("top_bar") is not True or layout.get("control_panel") is not True:
        issues.append(PageIssue("layout", "missing_panels", "layout needs top_bar and control_panel"))
        ok = False
    quiz = layout.get("quiz_panel")
    if not isinstance(quiz, dict):
        issues.append(PageIssue("layout.quiz_panel", "missing_quiz_panel", "quiz_panel must be an object"))
        return False
    if quiz.get("width_px") != LAYOUT["quiz_width_px"]:
        issues.append(PageIssue("layout.quiz_panel.width_px", "bad_quiz_width", "quiz panel width must be 360px"))
        ok = False
    if quiz.get("max_height_px") != LAYOUT["quiz_max_height_px"]:
        issues.append(PageIssue("layout.quiz_panel.max_height_px", "bad_quiz_height", "quiz panel max height must be 380px"))
        ok = False
    if quiz.get("collapsible") is not True or quiz.get("floating_button") is not True:
        issues.append(
            PageIssue("layout.quiz_panel", "quiz_not_collapsible", "quiz panel must be collapsible with a floating button")
        )
        ok = False
    if not _is_number(quiz.get("transition_s")) or not _close(
        float(quiz["transition_s"]), LAYOUT["quiz_transition_s"]  # type: ignore[arg-type]
    ):
        issues.append(PageIssue("layout.quiz_panel.transition_s", "bad_quiz_transition", "quiz transition must be 0.3s"))
        ok = False
    return ok


def _check_scene(
    spec: Mapping[str, Any], issues: list[PageIssue], atlas_model_names: Optional[Collection[str]]
) -> bool:
    render_mode = spec.get("render_mode")
    if render_mode not in ("three", "hybrid"):
        return True
    scene = spec.get("scene")
    if not isinstance(scene, dict):
        issues.append(PageIssue("scene", "missing_scene", "three/hybrid pages need a scene baseline"))
        return False
    ok = True
    camera = scene.get("camera")
    if (
        not isinstance(camera, dict)
        or camera.get("fov") != 60
        or not _is_number(camera.get("near"))
        or not _close(float(camera["near"]), 0.1)  # type: ignore[arg-type]
        or not _is_number(camera.get("far"))
        or not _close(float(camera["far"]), 1000.0)  # type: ignore[arg-type]
    ):
        issues.append(PageIssue("scene.camera", "bad_camera", "camera must be fov 60, near 0.1, far 1000"))
        ok = False
    lights = scene.get("lights")
    if not isinstance(lights, list):
        issues.append(PageIssue("scene.lights", "bad_lights", "lights must be a list"))
        ok = False
    else:
        types = [light.get("type") for light in lights if isinstance(light, dict)]
        if "hemisphere" not in types or "directional" not in types:
            issues.append(PageIssue("scene.lights", "missing_lights", "scene needs hemisphere and directional lights"))
            ok = False
        for light in lights:
            if isinstance(light, dict) and light.get("type") == "directional" and light.get("cast_shadow") is not True:
                issues.append(PageIssue("scene.lights", "bad_directional", "directional light must cast shadows"))
                ok = False
    renderer = scene.get("renderer")
    if not isinstance(renderer, dict) or renderer.get("antialias") is not True or renderer.get("shadow_map") is not True:
        issues.append(PageIssue("scene.renderer", "bad_renderer", "renderer needs antialias and shadow_map"))
        ok = False
    # 物理学科：场景语义归 Atlas，不另起规范；只要求指到注册模型名。
    if spec.get("subject") == "physics":
        ref = spec.get("atlas_model_ref")
        if atlas_model_names is None:
            issues.append(
                PageIssue("atlas_model_ref", "atlas_models_unchecked", "Atlas model names were not supplied for verification")
            )
            ok = False
        elif not isinstance(ref, str) or ref not in atlas_model_names:
            issues.append(
                PageIssue("atlas_model_ref", "unknown_atlas_model", "physics pages must reference a registered Atlas model")
            )
            ok = False
        return ok
    for pos, vector in enumerate(scene.get("vectors") or []):
        field = f"scene.vectors[{pos}]"
        if not isinstance(vector, dict):
            issues.append(PageIssue(field, "not_an_object", "vector must be an object"))
            ok = False
            continue
        quantity = vector.get("quantity")
        if quantity not in VECTOR_COLORS:
            issues.append(PageIssue(field, "bad_vector_quantity", "vector quantity must be force, velocity, or acceleration"))
            ok = False
        elif vector.get("color") != VECTOR_COLORS[quantity]:
            issues.append(PageIssue(field, "bad_vector_color", f"{quantity} vectors must use {VECTOR_COLORS[quantity]}"))
            ok = False
    return ok


def _check_dependencies(spec: Mapping[str, Any], issues: list[PageIssue]) -> bool:
    deps = spec.get("dependencies")
    if not isinstance(deps, dict):
        issues.append(PageIssue("dependencies", "missing_dependencies", "dependencies must be an object"))
        return False
    profile = deps.get("profile")
    libraries = deps.get("libraries")
    if profile not in ("self_hosted", "cdn_pinned"):
        issues.append(PageIssue("dependencies.profile", "bad_profile", "profile must be self_hosted or cdn_pinned"))
        return False
    if not isinstance(libraries, list) or not libraries:
        issues.append(PageIssue("dependencies.libraries", "missing_libraries", "libraries must be a non-empty list"))
        return False
    ok = True
    if profile == "self_hosted":
        if deps.get("requires_network") is not False:
            issues.append(PageIssue("dependencies.requires_network", "bad_network_flag", "self_hosted pages must not require network"))
            ok = False
        for pos, lib in enumerate(libraries):
            field = f"dependencies.libraries[{pos}]"
            if not isinstance(lib, dict):
                issues.append(PageIssue(field, "not_an_object", "library must be an object"))
                ok = False
                continue
            name = lib.get("library")
            if name == "tailwind":
                issues.append(PageIssue(field, "tailwind_forbidden", "self_hosted pages must not use Tailwind (inline styles instead)"))
                ok = False
                continue
            expected = SELF_HOSTED_LIBS.get(name) if isinstance(name, str) else None
            if expected is None:
                issues.append(PageIssue(field, "unknown_library", f"unknown self-hosted library: {name!r}"))
                ok = False
            elif lib.get("version") != expected["version"] or lib.get("url") != expected["url"]:
                issues.append(
                    PageIssue(field, "bad_library_pin", f"{name} must be {expected['version']} at {expected['url']}")
                )
                ok = False
    else:
        if deps.get("requires_network") is not True:
            issues.append(PageIssue("dependencies.requires_network", "bad_network_flag", "cdn_pinned pages require network"))
            ok = False
        if deps.get("offline_available") is not False:
            issues.append(PageIssue("dependencies.offline_available", "offline_claim", "cdn_pinned pages are not available offline"))
            ok = False
        for pos, lib in enumerate(libraries):
            field = f"dependencies.libraries[{pos}]"
            if not isinstance(lib, dict):
                issues.append(PageIssue(field, "not_an_object", "library must be an object"))
                ok = False
                continue
            name = lib.get("library")
            if name not in CDN_PINNED:
                issues.append(PageIssue(field, "unknown_library", f"unknown CDN library: {name!r}"))
                ok = False
                continue
            version = lib.get("version")
            if name == "tailwind":
                minor = re.match(r"^v3\.(\d+)", version) if isinstance(version, str) else None
                if minor is None or int(minor.group(1)) < 4:
                    issues.append(PageIssue(field, "bad_library_pin", "tailwind must be pinned to v3.4+"))
                    ok = False
            elif version != CDN_PINNED[name]:
                issues.append(PageIssue(field, "bad_library_pin", f"{name} must be pinned to {CDN_PINNED[name]}"))
                ok = False
            url = lib.get("url")
            if not isinstance(url, str) or not any(h in url for h in ALLOWED_CDN_HOSTS):
                issues.append(PageIssue(field, "bad_cdn_host", "CDN url host is not on the allowlist"))
                ok = False
            if not isinstance(lib.get("integrity"), str) or not lib["integrity"].strip():
                issues.append(
                    PageIssue(field, "missing_sri", "CDN libraries need an SRI integrity hash (gap: upstream ships none)")
                )
                ok = False
    return ok


def _normalize_ledger_result(result: object) -> tuple[bool, list[PageIssue]]:
    """接受 LedgerCheck 形态（.passed/.issues，元素带 to_dict）或 dict 形态。"""
    if isinstance(result, dict):
        passed = result.get("passed") is True
        raw_issues = result.get("issues") or []
        issues = []
        for item in raw_issues if isinstance(raw_issues, list) else []:
            if isinstance(item, dict):
                issues.append(PageIssue(str(item.get("field", "")), str(item.get("code", "ledger_issue")), str(item.get("message", ""))))
            else:
                issues.append(PageIssue("source_ledger", "ledger_issue", str(item)))
        return passed, issues
    passed = bool(getattr(result, "passed", False))
    issues = []
    for item in getattr(result, "issues", []) or []:
        if hasattr(item, "to_dict"):
            d = item.to_dict()
            issues.append(PageIssue(str(d.get("field", "")), str(d.get("code", "ledger_issue")), str(d.get("message", ""))))
        elif isinstance(item, dict):
            issues.append(PageIssue(str(item.get("field", "")), str(item.get("code", "ledger_issue")), str(item.get("message", ""))))
        else:
            issues.append(PageIssue("source_ledger", "ledger_issue", str(item)))
    return passed, issues


def verify_interactive_page(
    spec: object,
    *,
    known_ku_ids: Optional[set[str]] = None,
    known_textbook_ids: Optional[set[str]] = None,
    ledger_check: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    atlas_model_names: Optional[Collection[str]] = None,
) -> PageCheck:
    """页级校验门：g1–g10 全过才通过，失败逐条列原因（fail-closed）。

    ledger_check：调用方注入的台账门禁 verify_lesson_source_ledger
   （台账分支合入 main 后由路由层传入）。未注入时 g10 直接不过，
    不把“没接门禁”当成“通过”。atlas_model_names 未传时，物理学科
    默认取 Atlas 注册表（services.physics_models）；取不到则 g5 不过。
    """
    gates: dict[str, bool] = {f"g{i}": True for i in range(1, 11)}
    issues: list[PageIssue] = []

    def fail(gate: str, issue: PageIssue) -> None:
        gates[gate] = False
        issues.append(issue)

    if not isinstance(spec, dict):
        return PageCheck(gates, [PageIssue("", "not_an_object", "spec must be an object")])

    # g1：schema 与锚点 KU（fail-closed：不传已知集即判未核验）。
    spec_id = spec.get("id")
    if not isinstance(spec_id, str) or not _ID_RE.match(spec_id):
        fail("g1", PageIssue("id", "bad_id", "id must be a slug: [a-z0-9][a-z0-9_-]{0,99}"))
    if "verified" in spec:
        fail("g1", PageIssue("verified", "verified_field_forbidden", "verified is set by the server-side gate only"))
    if not _bilingual(spec.get("title")):
        fail("g1", PageIssue("title", "bad_title", "title must carry non-empty zh and en"))
    topic = spec.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        fail("g1", PageIssue("topic", "bad_topic", "topic must be a non-empty string"))
        topic = ""
    language = spec.get("language")
    if language not in ("zh", "en"):
        fail("g1", PageIssue("language", "bad_language", "language must be zh or en"))
    elif topic and bool(_CJK_RE.search(topic)) != (language == "zh"):
        fail("g1", PageIssue("language", "bad_language", "language must match the topic language"))
    ku_id = spec.get("ku_id")
    if not isinstance(ku_id, str) or not ku_id.strip():
        fail("g1", PageIssue("ku_id", "bad_ku_id", "ku_id must be a non-empty string"))
    elif known_ku_ids is None:
        fail("g1", PageIssue("ku_id", "ku_existence_unchecked", "KU anchor cannot be verified without a known set"))
    elif ku_id not in known_ku_ids:
        fail("g1", PageIssue("ku_id", "unknown_ku", f"knowledge unit {ku_id!r} does not exist"))

    # g2：布局（30/70、测验面板 360x380、可折叠+悬浮按钮、0.3s 过渡）。
    before = len(issues)
    _check_layout(spec, issues)
    if len(issues) > before:
        gates["g2"] = False

    # g3：学科与配色档。
    subject = spec.get("subject")
    if subject not in SUBJECTS:
        fail("g3", PageIssue("subject", "bad_subject", f"subject must be one of {SUBJECTS}"))
    elif spec.get("palette_family") != SUBJECT_PALETTES[subject]:
        fail("g3", PageIssue("palette_family", "bad_palette", f"{subject} pages use the {SUBJECT_PALETTES[subject]} palette family"))

    # g4：渲染模式（声明须与识别一致；不一致须书面说明覆盖原因）。
    render_mode = spec.get("render_mode")
    if render_mode not in RENDER_MODES:
        fail("g4", PageIssue("render_mode", "bad_render_mode", f"render_mode must be one of {RENDER_MODES}"))
    elif topic:
        try:
            detected = detect_render_mode(topic)
        except ValueError:
            detected = None
        if detected is not None and render_mode != detected:
            reason = spec.get("render_mode_override_reason")
            if not isinstance(reason, str) or not reason.strip():
                fail(
                    "g4",
                    PageIssue(
                        "render_mode",
                        "render_mode_mismatch",
                        f"render_mode {render_mode!r} differs from detected {detected!r}; give render_mode_override_reason",
                    ),
                )
    if render_mode in ("svg", "hybrid") and not isinstance(spec.get("svg_layer"), dict):
        fail("g4", PageIssue("svg_layer", "missing_svg_layer", "svg/hybrid pages need an svg_layer declaration"))
    if render_mode in ("three", "hybrid") and not isinstance(spec.get("scene"), dict):
        fail("g4", PageIssue("scene", "missing_scene", "three/hybrid pages need a scene declaration"))

    # g5：场景基线（物理归 Atlas；带 figures 时每张图过 teachable-figures 门）。
    before = len(issues)
    names = atlas_model_names
    if names is None and subject == "physics":
        try:
            from services.physics_models import PHYSICS_MODEL_REGISTRY

            names = set(PHYSICS_MODEL_REGISTRY)
        except ImportError:
            names = None
    _check_scene(spec, issues, names)
    figures = spec.get("figures")
    if figures is not None:
        if not isinstance(figures, list) or not figures:
            fail("g5", PageIssue("figures", "bad_figures", "figures must be a non-empty list when present"))
        else:
            for pos, figure in enumerate(figures):
                result = verify_figure(figure, known_ku_ids=known_ku_ids)
                if not result.passed:
                    for item in result.issues:
                        fail(
                            "g5",
                            PageIssue(f"figures[{pos}].{item.field}", item.code, item.message),
                        )
    if len(issues) > before:
        gates["g5"] = False

    # g6：依赖 profile（self_hosted 首选；cdn_pinned 须钉死版本 + SRI）。
    before = len(issues)
    _check_dependencies(spec, issues)
    if len(issues) > before:
        gates["g6"] = False

    # g7：输出契约（单文件 HTML、无额外文件、不包 markdown）。
    output = spec.get("output")
    if not isinstance(output, dict):
        fail("g7", PageIssue("output", "missing_output", "output must be an object"))
    else:
        if output.get("single_file_html") is not True:
            fail("g7", PageIssue("output.single_file_html", "not_single_file", "output must be a single HTML file"))
        file_name = output.get("file_name")
        if not isinstance(file_name, str) or not file_name.endswith(".html"):
            fail("g7", PageIssue("output.file_name", "bad_file_name", "file_name must end with .html"))
        if output.get("extra_files") not in (None, []):
            fail("g7", PageIssue("output.extra_files", "extra_files", "output must not carry extra files"))
        if output.get("wraps_markdown") is not False:
            fail("g7", PageIssue("output.wraps_markdown", "wraps_markdown", "output must not be wrapped in markdown"))

    # g8：交互控件契约。
    before = len(issues)
    issues.extend(validate_controls(spec.get("controls")))
    if len(issues) > before:
        gates["g8"] = False

    # g9：断言出处（citation_check）+ provenance 档位。
    assertions = spec.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        fail("g9", PageIssue("assertions", "missing_assertions", "assertions must be a non-empty list"))
    else:
        checked = check_citations(
            assertions, known_ku_ids=known_ku_ids, known_textbook_ids=known_textbook_ids
        )
        if not checked["passed"]:
            # check_citations 的顶层 issues 恒为空，明细在 segments[].issues 里。
            for seg in checked.get("segments", []):
                for item in seg.get("issues", []):
                    fail("g9", PageIssue(f"assertions.{item['field']}", item["code"], item["message"]))
    provenance = spec.get("provenance")
    if not isinstance(provenance, dict):
        fail("g9", PageIssue("provenance", "missing_provenance", "provenance must be an object"))
    else:
        label = provenance.get("label")
        if label not in {item.value for item in ProvenanceLabel}:
            fail("g9", PageIssue("provenance.label", "bad_label", "provenance label is not one of the three tiers"))
        sources = provenance.get("sources")
        if not isinstance(sources, list):
            fail("g9", PageIssue("provenance.sources", "bad_sources", "provenance sources must be a list"))
        elif label == ProvenanceLabel.MATERIAL.value and not sources:
            fail("g9", PageIssue("provenance.sources", "material_needs_source", "MATERIAL provenance needs at least one source"))

    # g10：出处台账门禁（注入式；未注入即不过，不放行）。
    ledger = spec.get("source_ledger")
    if not isinstance(ledger, dict) or not ledger:
        fail("g10", PageIssue("source_ledger", "missing_ledger", "interactive pages must carry a source ledger"))
    elif ledger_check is None:
        fail(
            "g10",
            PageIssue(
                "source_ledger",
                "ledger_gate_unavailable",
                "source-ledger gate is not wired in this branch (merge feat/narration-source-ledger-g1 first)",
            ),
        )
    else:
        try:
            ledger_passed, ledger_issues = _normalize_ledger_result(ledger_check(spec))
        except Exception as exc:  # noqa: BLE001 — 门禁抛错当不过，不让异常变放行
            fail("g10", PageIssue("source_ledger", "ledger_check_error", f"ledger gate raised {type(exc).__name__}"))
            ledger_passed, ledger_issues = False, []
        if not ledger_passed:
            for item in ledger_issues:
                fail("g10", PageIssue(f"source_ledger.{item.field}", item.code, item.message))
            if not ledger_issues:
                fail("g10", PageIssue("source_ledger", "ledger_failed", "source-ledger gate failed"))

    return PageCheck(gates, issues)


def _default_controls() -> list[dict[str, Any]]:
    return [
        {"kind": "slider", "enabled": True, "min": 0, "max": 10, "step": 0.1, "value": 5},
        {"kind": "play", "enabled": True},
        {"kind": "pause", "enabled": True},
        {"kind": "step", "enabled": True},
        {"kind": "speed", "enabled": True, "options": [0.5, 1.0, 2.0], "value": 1.0},
        {"kind": "reset", "enabled": True},
        {"kind": "random_experiment", "enabled": False},
        {
            "kind": "objectives_checklist",
            "enabled": True,
            "items": ["说出牛顿第二定律", "算出给定力下的加速度", "解释质量对加速度的影响"],
        },
        {"kind": "click_highlight", "enabled": True},
    ]


def example_spec(
    ku_id: str = "ku-newton-2nd-law",
    *,
    topic: str = "牛顿第二定律",
    subject: str = "physics",
    render_mode: str = "hybrid",
) -> dict[str, Any]:
    """一个能过门的示例规格（牛顿第二定律，物理，hybrid，Atlas 平抛模型挂接）。

    注意：atlas_model_ref 用 projectile_motion 只为演示“指到注册模型”
    这一门禁形状，不代表该模型就是本主题的教学模型；真接主题时须换
    与主题一致的 Atlas 模型名。调用方须另传 known_ku_ids（含 ku_id）
    与 ledger_check，门禁才放行。
    """
    return {
        "id": "ip-newton-2nd-law",
        "ku_id": ku_id,
        "title": {"zh": "牛顿第二定律", "en": "Newton's Second Law"},
        "language": "zh",
        "topic": topic,
        "subject": subject,
        "palette_family": SUBJECT_PALETTES[subject],
        "render_mode": render_mode,
        "layout": {
            "sidebar_ratio": 0.30,
            "canvas_ratio": 0.70,
            "top_bar": True,
            "control_panel": True,
            "quiz_panel": {
                "width_px": 360,
                "max_height_px": 380,
                "collapsible": True,
                "floating_button": True,
                "transition_s": 0.3,
            },
        },
        "scene": {
            "camera": {"fov": 60, "near": 0.1, "far": 1000},
            "lights": [{"type": "hemisphere"}, {"type": "directional", "cast_shadow": True}],
            "renderer": {"antialias": True, "shadow_map": True},
        },
        "svg_layer": {"overlay": True},
        "atlas_model_ref": "projectile_motion",
        "dependencies": {
            "profile": "self_hosted",
            "requires_network": False,
            "offline_available": True,
            "libraries": [
                {"library": "three", "version": "0.134.0", "url": "/v1/edu-assets/three-0.134.0/three.min.js"},
                {"library": "katex_js", "version": "0.16.8", "url": "/v1/edu-assets/katex-0.16.8/katex.min.js"},
                {"library": "d3", "version": "7.9.0", "url": "/v1/edu-assets/d3-7.9.0/d3.min.js"},
            ],
        },
        "output": {"single_file_html": True, "file_name": "lesson.html", "extra_files": [], "wraps_markdown": False},
        "controls": _default_controls(),
        "assertions": [
            {"text": "合外力等于质量乘加速度", "refs": [{"kind": "ku", "id": ku_id}]},
        ],
        "provenance": {"label": "material", "sources": [{"kind": "ku", "id": ku_id}]},
        "source_ledger": {"rows": [{"shot": 0, "claim": "合外力等于质量乘加速度"}]},
    }
