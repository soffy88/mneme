"""教学图规格合同 + 真值模型接口 + 验证门。

teachable-figures（predict → try → explain）方法论的 Mneme 干净实现：
方法可学，代码自己写——未复制对方 SKILL 文本、示例或代码。

- 规格合同：一个 claim 一张图；预测选项含可证伪的误解；caveat 必填；
  数字三标签（来源事实 / 计算 / 示意参数）全覆盖。
- 真值模型：纯函数 initial_state / apply_action / derive（时间相关模型
  可加 step）；同一份派生结果 feeding 图、读数、摘要、讲解；语义态与
  视图态分离；非法输入 clamp、拒绝不可能状态，绝不编造看似合理的结果。
- 验证门 verify_figure：10 项全过才 verified；verified 只由服务端
  verify 调用重跑门禁后设置，写路径不接受客户端输入。

本模块是纯函数，无 DB、无网络、无 LLM 调用，可脱服务直测。
锚点 KU 的存在性由调用方以 known_ku_ids 传入（fail-closed：不传
即判锚点未核验，不通过）。
"""

from __future__ import annotations

import math
import random
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Collection, Mapping, Sequence

from services.provenance import ProvenanceLabel, SourceRef

RENDERER_HINTS = ("svg-2d", "iso-lite", "iso-mechanical", "turning-3d", "webgl")

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
_FIGURE_KEY_RE = re.compile(r"^figures/[A-Za-z0-9_.\-]+/p\d+_\d+\.png$")
_BILINGUAL_FIELDS = ("title", "lead", "insight", "caveat", "frame")
_STRUCTURAL_NUMBER_KEYS = ("answer_index", "seed", "tolerance")


class NumberKind(str, Enum):
    """数字三标签：来源事实 / 计算结果 / 示意参数。"""

    SOURCE_FACT = "source_fact"
    CALCULATION = "calculation"
    ILLUSTRATIVE = "illustrative"


class ImpossibleStateError(ValueError):
    """模型拒绝不可能的状态（不编造看似合理的结果）。"""


@dataclass(frozen=True)
class TaggedNumber:
    """一个带档位的数值：值 + 单位 + 档位 + 说明。

    note 在三个档位都必填：来源事实写引用、计算写公式与假设、
    示意参数写明“为教学所选”。JSON 形态为
    {"value": .., "unit": "..", "kind": "..", "note": ".."}。
    """

    value: float
    unit: str
    kind: NumberKind
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "unit": self.unit,
            "kind": self.kind.value,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, raw: object) -> "TaggedNumber":
        if not isinstance(raw, dict):
            raise TypeError("tagged number must be an object")
        value = raw.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("tagged number value must be numeric")
        if not math.isfinite(value):
            raise ValueError("tagged number value must be finite")
        kind_raw = raw.get("kind")
        try:
            kind = NumberKind(kind_raw)
        except ValueError as exc:
            raise ValueError(f"unknown number kind: {kind_raw!r}") from exc
        unit = raw.get("unit")
        if not isinstance(unit, str):
            raise TypeError("tagged number unit must be a string")
        note = raw.get("note", "")
        if not isinstance(note, str) or not note.strip():
            raise ValueError("tagged number note must be a non-empty string")
        return cls(value=float(value), unit=unit, kind=kind, note=note)


def _is_tagged_number_dict(raw: object) -> bool:
    return (
        isinstance(raw, dict)
        and "value" in raw
        and "kind" in raw
        and set(raw.keys()) <= {"value", "unit", "kind", "note"}
    )


def _is_number(raw: object) -> bool:
    return isinstance(raw, (int, float)) and not isinstance(raw, bool)


def find_untagged_numbers(
    obj: object, path: str = "$"
) -> list[str]:
    """找出规格中未带三标签的数值，返回其路径。

    跳过结构性数值：answer_index（选项下标）、seed（采样种子）、
    tolerance（比较容差）、actions 子树（运行期学习者输入，非规格量）。
    """
    problems: list[str] = []
    if _is_tagged_number_dict(obj):
        try:
            TaggedNumber.from_dict(obj)
        except (TypeError, ValueError) as exc:
            problems.append(f"{path}: malformed tagged number ({exc})")
        return problems
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in _STRUCTURAL_NUMBER_KEYS or key == "actions":
                continue
            problems.extend(find_untagged_numbers(val, f"{path}.{key}"))
        return problems
    if isinstance(obj, list):
        for i, val in enumerate(obj):
            problems.extend(find_untagged_numbers(val, f"{path}[{i}]"))
        return problems
    if _is_number(obj):
        problems.append(f"{path}: untagged number {obj!r}")
    return problems


# ── 真值模型协议 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ModelParameter:
    """模型参数声明：单位、档位、边界显式；越界 clamp，越界且
    minimum_exclusive 时 initial_state 拒绝（不可能状态）。"""

    name: str
    dtype: str = "number"  # number | flag | text
    unit: str = ""
    kind: NumberKind | None = None
    minimum: float | None = None
    maximum: float | None = None
    minimum_exclusive: bool = False
    maximum_exclusive: bool = False
    required: bool = True


@dataclass(frozen=True)
class ExpectedOutcome:
    """作者陈述的期望：给定参数与动作序列，派生结果须与之一致。"""

    name: str
    actions: tuple[dict, ...] = ()
    expected: Mapping[str, TaggedNumber | str] = field(default_factory=dict)


class TruthModel(ABC):
    """纯函数真值模型：同一份 derive 结果 feeding 图、读数、摘要、讲解。

    状态只含语义量（视图态不得进入 state）；apply_action 返回新状态，
    不原地改；显示 easing 与语义分离（easing 不在本层出现）。
    """

    name: str = ""
    parameters: tuple[ModelParameter, ...] = ()
    stochastic: bool = False

    def bind_parameters(
        self, raw: Mapping[str, object]
    ) -> tuple[dict[str, TaggedNumber | bool | str], list[str], list[str]]:
        """把规格参数绑定为模型可用形态。

        返回 (bound, issues, clamped)：未知/缺失/档位错 → issues；
        越界 → clamp 并记入 clamped（不是 issue，但须可观测）。
        """
        bound: dict[str, TaggedNumber | bool | str] = {}
        issues: list[str] = []
        clamped: list[str] = []
        declared = {p.name: p for p in self.parameters}
        for key in raw:
            if key not in declared:
                issues.append(f"model parameter {key!r} is not declared")
        for param in self.parameters:
            if param.name not in raw:
                if param.required:
                    issues.append(f"missing required model parameter {param.name!r}")
                continue
            value = raw[param.name]
            if param.dtype == "flag":
                if not isinstance(value, bool):
                    issues.append(f"model parameter {param.name!r} must be a boolean")
                    continue
                bound[param.name] = value
                continue
            if param.dtype == "text":
                if not isinstance(value, str):
                    issues.append(f"model parameter {param.name!r} must be a string")
                    continue
                bound[param.name] = value
                continue
            try:
                tagged = TaggedNumber.from_dict(value)
            except (TypeError, ValueError) as exc:
                issues.append(f"model parameter {param.name!r}: {exc}")
                continue
            if param.kind is not None and tagged.kind != param.kind:
                issues.append(
                    f"model parameter {param.name!r} must be tagged "
                    f"{param.kind.value}, got {tagged.kind.value}"
                )
                continue
            if param.unit and tagged.unit != param.unit:
                issues.append(
                    f"model parameter {param.name!r} must use unit "
                    f"{param.unit!r}, got {tagged.unit!r}"
                )
                continue
            clamped_value = tagged.value
            if param.minimum is not None:
                if clamped_value < param.minimum or (
                    param.minimum_exclusive and clamped_value == param.minimum
                ):
                    clamped_value = param.minimum
                    clamped.append(param.name)
            if param.maximum is not None:
                if clamped_value > param.maximum or (
                    param.maximum_exclusive and clamped_value == param.maximum
                ):
                    clamped_value = param.maximum
                    clamped.append(param.name)
            bound[param.name] = TaggedNumber(
                clamped_value, tagged.unit, tagged.kind, tagged.note
            )
        return bound, issues, clamped

    @abstractmethod
    def initial_state(
        self, config: Mapping[str, TaggedNumber | bool | str]
    ) -> dict:
        """给定绑定后参数，返回初始语义态。"""

    @abstractmethod
    def apply_action(self, state: Mapping, action: Mapping) -> dict:
        """施加一个学习者动作，返回新语义态（不改原 state）。"""

    @abstractmethod
    def derive(self, state: Mapping) -> dict:
        """同一份派生结果：数值须为 TaggedNumber，字符串为代码值。"""

    def step(self, state: Mapping, dt_seconds: float) -> dict:
        """时间相关模型推进 dt 秒；默认无时间演化，原样返回。"""
        return dict(state)

    def sample(self, seed: int, n: int) -> dict:
        """随机模型：返回 {"expected": {...}, "sampled": {...}}。

        期望分布与采样结果分开陈述；同一种子须可复现。非随机模型
        不必实现（stochastic=False 时门禁不调用）。
        """
        raise NotImplementedError("this model is not stochastic")


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


class ProportionalOutputModel(TruthModel):
    """比例关系模型（Mneme 自有 K12 内容）：输出量＝输入量×比值。

    齿数比的情形：主动轮齿数 / 从动轮齿数；外啮合齿轮组反向
    （符号为负），方向语义由 reverses_direction 承载。
    公式自述：output = sign × input × driver_teeth / driven_teeth，
    其中 sign = -1（反向）或 +1（同向）。
    """

    name = "proportional_output"
    parameters = (
        ModelParameter(
            "driver_teeth", unit="teeth", kind=NumberKind.SOURCE_FACT,
            minimum=1,
        ),
        ModelParameter(
            "driven_teeth", unit="teeth", kind=NumberKind.SOURCE_FACT,
            minimum=1,
        ),
        ModelParameter("reverses_direction", dtype="flag"),
    )

    def initial_state(self, config):
        driven = config["driven_teeth"]
        if driven.value <= 0:
            raise ImpossibleStateError("driven_teeth must be positive")
        return {
            "input_turns": 0.0,
            "driver_teeth": int(config["driver_teeth"].value),
            "driven_teeth": int(driven.value),
            "reverses_direction": bool(config["reverses_direction"]),
        }

    def apply_action(self, state, action):
        if action.get("kind") != "turn":
            raise ImpossibleStateError(f"unknown action: {action.get('kind')!r}")
        turns = action.get("turns")
        if _is_number(turns) is False:
            raise ImpossibleStateError("turn action requires numeric turns")
        new_state = dict(state)
        new_state["input_turns"] = state["input_turns"] + _clamp(
            float(turns), -100.0, 100.0
        )
        return new_state

    def derive(self, state):
        ratio = state["driver_teeth"] / state["driven_teeth"]
        sign = -1.0 if state["reverses_direction"] else 1.0
        return {
            "ratio": TaggedNumber(
                ratio, "1", NumberKind.CALCULATION,
                "比值＝主动轮齿数/从动轮齿数",
            ),
            "output_turns": TaggedNumber(
                sign * state["input_turns"] * ratio,
                "turn", NumberKind.CALCULATION,
                "输出圈数＝符号×输入圈数×齿数比",
            ),
            "direction": "反向" if state["reverses_direction"] else "同向",
        }


class QuadraticGrowthModel(TruthModel):
    """二次增长模型（Mneme 自有 K12 内容）：面积随线性量二次增长。

    公式自述：area = coefficient × size²。系数为计算值（如正方形
    系数 1、圆形系数 π）；size_limit 为教学所选的示意上限。
    """

    name = "quadratic_growth"
    parameters = (
        ModelParameter(
            "coefficient", unit="1", kind=NumberKind.CALCULATION,
            minimum=0.0, minimum_exclusive=True,
        ),
        ModelParameter(
            "size_limit", unit="cm", kind=NumberKind.ILLUSTRATIVE,
            minimum=0.0, minimum_exclusive=True,
        ),
    )

    def initial_state(self, config):
        coefficient = config["coefficient"]
        if coefficient.value <= 0:
            raise ImpossibleStateError("coefficient must be positive")
        return {
            "size": 0.0,
            "coefficient": coefficient.value,
            "size_limit": config["size_limit"].value,
        }

    def apply_action(self, state, action):
        if action.get("kind") != "set_size":
            raise ImpossibleStateError(f"unknown action: {action.get('kind')!r}")
        size = action.get("size")
        if _is_number(size) is False:
            raise ImpossibleStateError("set_size action requires numeric size")
        if float(size) < 0:
            raise ImpossibleStateError("size cannot be negative")
        new_state = dict(state)
        new_state["size"] = _clamp(float(size), 0.0, state["size_limit"])
        return new_state

    def derive(self, state):
        size = state["size"]
        return {
            "size": TaggedNumber(
                size, "cm", NumberKind.CALCULATION, "当前边长（学习者设定）"
            ),
            "area": TaggedNumber(
                state["coefficient"] * size * size,
                "cm²", NumberKind.CALCULATION, "面积＝系数×边长²",
            ),
        }


MODEL_REGISTRY: dict[str, TruthModel] = {
    ProportionalOutputModel.name: ProportionalOutputModel(),
    QuadraticGrowthModel.name: QuadraticGrowthModel(),
}


# ── 随机性口径：种子可复现、期望与采样分开 ──────────────────────────────


def expected_distribution(weights: Sequence[float]) -> list[float]:
    """期望分布：权重归一化，和为 1；全零/负权重拒绝，不编结果。"""
    if not weights:
        raise ImpossibleStateError("weights must not be empty")
    if any(w < 0 for w in weights):
        raise ImpossibleStateError("weights must not be negative")
    total = sum(weights)
    if total <= 0:
        raise ImpossibleStateError("weights must sum to a positive value")
    return [w / total for w in weights]


def seeded_sample(seed: int, weights: Sequence[float], n: int) -> list[int]:
    """种子可复现的采样：同一种子、同一权重、同一 n，结果恒相同。"""
    if n < 0:
        raise ImpossibleStateError("n must not be negative")
    probs = expected_distribution(weights)
    rng = random.Random(seed)
    cuts = [sum(probs[: i + 1]) for i in range(len(probs))]
    out = []
    for _ in range(n):
        r = rng.random()
        out.append(next(i for i, c in enumerate(cuts) if r < c))
    return out


# ── 规格合同与验证门 ─────────────────────────────────────────────────────


@dataclass
class ValidationIssue:
    field: str
    code: str
    message: str


@dataclass
class ValidationResult:
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    gates: dict[str, bool] = field(default_factory=dict)


def _bilingual_text(
    value: object, field_name: str, issues: list[ValidationIssue]
) -> dict[str, str] | None:
    if not isinstance(value, dict):
        issues.append(
            ValidationIssue(field_name, "not_bilingual",
                            f"{field_name} must be an object with zh and en text")
        )
        return None
    zh = value.get("zh")
    en = value.get("en")
    ok = True
    for lang, text in (("zh", zh), ("en", en)):
        if not isinstance(text, str) or not text.strip():
            issues.append(
                ValidationIssue(field_name, "missing_language",
                                f"{field_name}.{lang} must be a non-empty string")
            )
            ok = False
    return {"zh": zh, "en": en} if ok else None


def _check_expectations(
    model: TruthModel,
    bound: Mapping[str, TaggedNumber | bool | str],
    raw_expected: object,
    issues: list[ValidationIssue],
) -> None:
    """门禁第 6 项：期望须 ≥2 条、含复位态与跃迁态，且逐条与模型一致。"""
    if not isinstance(raw_expected, list) or not raw_expected:
        issues.append(
            ValidationIssue("model_ref.expected", "expected_required",
                            "model_ref.expected must list at least one expectation")
        )
        return
    if len(raw_expected) < 2:
        issues.append(
            ValidationIssue("model_ref.expected", "expected_too_few",
                            "at least two expectations are required: "
                            "reset state and a meaningful transition")
        )
    has_reset = False
    has_transition = False
    for idx, entry in enumerate(raw_expected):
        base = f"model_ref.expected[{idx}]"
        if not isinstance(entry, dict):
            issues.append(ValidationIssue(base, "bad_entry", "expectation must be an object"))
            continue
        actions = entry.get("actions")
        if not isinstance(actions, list):
            issues.append(ValidationIssue(base, "bad_actions", "actions must be a list"))
            continue
        if not actions:
            has_reset = True
        else:
            has_transition = True
        expected = entry.get("expected")
        if not isinstance(expected, dict) or not expected:
            issues.append(
                ValidationIssue(base, "bad_expected", "expected must be a non-empty object")
            )
            continue
        try:
            state = model.initial_state(bound)
            for action in actions:
                if not isinstance(action, dict):
                    raise ImpossibleStateError("action must be an object")
                state = model.apply_action(state, action)
            derived = model.derive(state)
        except ImpossibleStateError as exc:
            issues.append(
                ValidationIssue(base, "model_rejected", f"model rejected the case: {exc}")
            )
            continue
        for readout, want_raw in expected.items():
            if readout not in derived:
                issues.append(
                    ValidationIssue(base, "unknown_readout",
                                    f"model has no readout {readout!r}")
                )
                continue
            got = derived[readout]
            if isinstance(want_raw, str):
                if got != want_raw:
                    issues.append(
                        ValidationIssue(
                            base, "expectation_mismatch",
                            f"readout {readout!r}: expected {want_raw!r}, got {got!r}",
                        )
                    )
                continue
            try:
                want = TaggedNumber.from_dict(want_raw)
            except (TypeError, ValueError) as exc:
                issues.append(
                    ValidationIssue(base, "bad_expected_number",
                                    f"readout {readout!r}: {exc}")
                )
                continue
            if not isinstance(got, TaggedNumber):
                issues.append(
                    ValidationIssue(base, "readout_not_number",
                                    f"readout {readout!r} is not a tagged number")
                )
                continue
            tol = entry.get("tolerance", 1e-9)
            if not _is_number(tol):
                tol = 1e-9
            if (
                got.unit != want.unit
                or got.kind != want.kind
                or abs(got.value - want.value) > float(tol) + float(tol) * abs(want.value)
            ):
                issues.append(
                    ValidationIssue(
                        base, "expectation_mismatch",
                        f"readout {readout!r}: expected {want.value} {want.unit} "
                        f"({want.kind.value}), got {got.value} {got.unit} "
                        f"({got.kind.value})",
                    )
                )
    if not has_reset:
        issues.append(
            ValidationIssue("model_ref.expected", "no_reset_case",
                            "expectations must include a reset-state case (no actions)")
        )
    if not has_transition:
        issues.append(
            ValidationIssue("model_ref.expected", "no_transition_case",
                            "expectations must include a case with actions")
        )


def verify_figure(
    spec: object,
    *,
    known_ku_ids: Collection[str] | None = None,
    existing_ids: Collection[str] | None = None,
) -> ValidationResult:
    """验证门：10 项全过才 verified，失败逐条列原因。

    known_ku_ids 为 None 时锚点存在性无法核验，fail-closed。
    """
    issues: list[ValidationIssue] = []
    notes: list[str] = []
    gates: dict[str, bool] = {f"g{i}": True for i in range(1, 11)}

    def fail(gate: str, issue: ValidationIssue) -> None:
        gates[gate] = False
        issues.append(issue)

    if not isinstance(spec, dict):
        fail("g1", ValidationIssue("$", "not_object", "spec must be an object"))
        return ValidationResult(False, issues, notes, gates)

    # g1：schema 合法、id 唯一、必填齐全；verified 字段门禁自管。
    spec_id = spec.get("id")
    if not isinstance(spec_id, str) or not _ID_RE.match(spec_id):
        fail("g1", ValidationIssue("id", "bad_id",
                                   "id must be a slug: [a-z0-9][a-z0-9_-]{0,99}"))
    if existing_ids is not None and spec_id in existing_ids:
        fail("g1", ValidationIssue("id", "duplicate_id", f"id {spec_id!r} already exists"))
    if "verified" in spec:
        fail("g1", ValidationIssue("verified", "verified_field_forbidden",
                                   "verified is set by the server-side gate only"))
    required = ("ku_id", "title", "lead", "predict", "misconception", "config",
                "insight", "caveat", "frame", "language", "renderer_hint",
                "model_ref")
    for field_name in required:
        if field_name not in spec:
            fail("g1", ValidationIssue(field_name, "missing_field",
                                       f"missing required field {field_name!r}"))

    # g2：锚点 KU 真实存在。
    ku_id = spec.get("ku_id")
    if not isinstance(ku_id, str) or not ku_id.strip():
        fail("g2", ValidationIssue("ku_id", "bad_ku_id", "ku_id must be a non-empty string"))
    elif known_ku_ids is None:
        fail("g2", ValidationIssue("ku_id", "ku_existence_unchecked",
                                   "anchor existence was not checked"))
    elif ku_id not in known_ku_ids:
        fail("g2", ValidationIssue("ku_id", "ku_not_found",
                                   f"knowledge unit {ku_id!r} does not exist"))

    # g10：语言字段齐全（双语 copy + 主语言）。
    texts: dict[str, dict[str, str] | None] = {}
    for field_name in _BILINGUAL_FIELDS:
        if field_name in spec:
            texts[field_name] = _bilingual_text(spec[field_name], field_name, issues)
    if any(v is None for v in texts.values()):
        gates["g10"] = False
    language = spec.get("language")
    if language not in ("zh", "en"):
        fail("g10", ValidationIssue("language", "bad_language",
                                    "language must be 'zh' or 'en'"))
    misconception = None
    if "misconception" in spec:
        misconception = _bilingual_text(spec["misconception"], "misconception", issues)
        if misconception is None:
            gates["g10"] = False

    # g3：恰好一个最佳答案且选项 ≥2。
    best_index: int | None = None
    options: dict[str, list[str]] | None = None
    predict = spec.get("predict")
    if isinstance(predict, dict):
        options = {}
        for lang in ("zh", "en"):
            opts = predict.get(lang)
            if not isinstance(opts, list) or not all(
                isinstance(o, str) and o.strip() for o in opts
            ):
                fail("g3", ValidationIssue("predict", "bad_options",
                                           f"predict.{lang} must be a list of non-empty strings"))
                options = None
                break
            options[lang] = opts
        if options is not None:
            if not (2 <= len(options["zh"]) <= 4) or len(options["zh"]) != len(options["en"]):
                fail("g3", ValidationIssue("predict", "bad_option_count",
                                           "predict needs 2-4 options, same count in zh and en"))
                options = None
        if options is not None:
            answer_index = predict.get("answer_index")
            if isinstance(answer_index, bool) or not isinstance(answer_index, int):
                fail("g3", ValidationIssue("predict.answer_index", "bad_answer_index",
                                           "answer_index must be an integer"))
            elif not 0 <= answer_index < len(options["zh"]):
                fail("g3", ValidationIssue("predict.answer_index", "answer_index_out_of_range",
                                           "answer_index must point at one option"))
            else:
                best_index = answer_index
    elif "predict" in spec:
        fail("g3", ValidationIssue("predict", "bad_predict",
                                   "predict must be an object with zh/en options"))

    # g4：misconception 存在且与最佳答案不同。
    if misconception is not None and best_index is not None and options is not None:
        for lang in ("zh", "en"):
            if misconception[lang].strip() == options[lang][best_index].strip():
                fail("g4", ValidationIssue("misconception", "misconception_equals_answer",
                                           f"misconception.{lang} must differ from the best answer"))
    elif "misconception" in spec and misconception is not None:
        fail("g4", ValidationIssue("misconception", "misconception_unchecked",
                                   "misconception could not be compared without valid options"))

    # g5：caveat 非空且点明假设与类比边界（双语非空 + 长度下限；语义
    # 由作者自查，门禁只验“写了”不验“写得对”，如实记录于文档）。
    caveat = texts.get("caveat")
    if caveat is not None:
        for lang in ("zh", "en"):
            if len(caveat[lang].strip()) < 8:
                fail("g5", ValidationIssue("caveat", "caveat_too_short",
                                           f"caveat.{lang} must state assumptions and limits"))

    # g8：数字三标签全覆盖。
    for problem in find_untagged_numbers(spec):
        fail("g8", ValidationIssue("numbers", "untagged_number", problem))

    # g9：renderer_hint 在允许档内（仅提示，本次不实现渲染）。
    if spec.get("renderer_hint") not in RENDERER_HINTS:
        fail("g9", ValidationIssue("renderer_hint", "bad_renderer_hint",
                                   f"renderer_hint must be one of {RENDERER_HINTS}"))

    # g6/g7：模型期望 + 复位恢复 + 视图分离。
    model: TruthModel | None = None
    bound: Mapping[str, TaggedNumber | bool | str] | None = None
    model_ref = spec.get("model_ref")
    if isinstance(model_ref, dict):
        model_name = model_ref.get("model")
        model = MODEL_REGISTRY.get(model_name) if isinstance(model_name, str) else None
        if model is None:
            fail("g6", ValidationIssue("model_ref.model", "unknown_model",
                                       f"unknown truth model: {model_name!r}"))
        else:
            params = model_ref.get("parameters")
            if not isinstance(params, dict):
                fail("g6", ValidationIssue("model_ref.parameters", "bad_parameters",
                                           "parameters must be an object"))
            else:
                bound, bind_issues, clamped = model.bind_parameters(params)
                for msg in bind_issues:
                    fail("g6", ValidationIssue("model_ref.parameters", "bind_failed", msg))
                for name in clamped:
                    notes.append(f"parameter {name!r} was clamped to its declared bound")
            if bound is not None and not any(
                i.field == "model_ref.parameters" for i in issues
            ):
                _check_expectations(model, bound, model_ref.get("expected"), issues)
                if any(i.field.startswith("model_ref.expected") for i in issues):
                    gates["g6"] = False
                try:
                    initial = model.initial_state(bound)
                    derived0 = model.derive(initial)
                    initial_copy = dict(initial)
                    state = initial
                    for entry in model_ref.get("expected") or []:
                        if not isinstance(entry, dict):
                            continue
                        for action in entry.get("actions", []) or []:
                            if isinstance(action, dict):
                                state = model.apply_action(state, action)
                    if dict(initial) != initial_copy:
                        fail("g7", ValidationIssue("model", "state_mutated",
                                                   "apply_action must not mutate its input state"))
                    if model.derive(model.initial_state(bound)) != derived0:
                        fail("g7", ValidationIssue("model", "reset_not_restored",
                                                   "reset did not restore the initial derived state"))
                    view = spec.get("view")
                    if view is not None:
                        if not isinstance(view, dict):
                            fail("g7", ValidationIssue("view", "bad_view",
                                                       "view must be an object"))
                        elif set(view) & set(initial):
                            fail("g7", ValidationIssue("view", "view_state_leak",
                                                       "view keys must not overlap semantic state keys"))
                except ImpossibleStateError as exc:
                    fail("g6", ValidationIssue("model", "model_rejected",
                                               f"model rejected the bound config: {exc}"))
                if model.stochastic:
                    try:
                        first = model.sample(seed=7, n=20)
                        second = model.sample(seed=7, n=20)
                        if first != second or "expected" not in first or "sampled" not in first:
                            fail("g6", ValidationIssue("model", "stochastic_not_reproducible",
                                                       "stochastic model must be seed-reproducible "
                                                       "and report expected vs sampled separately"))
                    except NotImplementedError:
                        fail("g6", ValidationIssue("model", "stochastic_no_sample",
                                                   "stochastic model must implement sample()"))
    elif "model_ref" in spec:
        fail("g6", ValidationIssue("model_ref", "bad_model_ref",
                                   "model_ref must be an object"))

    # 设计注记（作者自查项，非必填、不判分）：缺失只记 note。
    design_note = spec.get("design_note")
    if design_note is None:
        notes.append("design_note is absent: author checks (meaningful try, "
                     "explanation points, transfer case) are not recorded")
    elif isinstance(design_note, dict):
        points = design_note.get("explanation_points")
        if points is not None and (
            not isinstance(points, list) or len(points) != 2
        ):
            fail("g1", ValidationIssue("design_note.explanation_points", "bad_points",
                                       "explanation_points must list exactly two points"))
    else:
        fail("g1", ValidationIssue("design_note", "bad_design_note",
                                   "design_note must be an object"))

    # figure_refs（可选）：只验对象键形态，存在性属渲染/存储集成待接点。
    figure_refs = spec.get("figure_refs")
    if figure_refs is not None:
        if not isinstance(figure_refs, list):
            fail("g1", ValidationIssue("figure_refs", "bad_figure_refs",
                                       "figure_refs must be a list"))
        else:
            for idx, ref in enumerate(figure_refs):
                if not isinstance(ref, dict) or not _FIGURE_KEY_RE.match(
                    str(ref.get("object_key", ""))
                ):
                    fail("g1", ValidationIssue(f"figure_refs[{idx}]", "bad_object_key",
                                               "object_key must look like "
                                               "figures/<doc>/p<page>_<index>.png"))

    # misconception 可带可选错题引用（字符串，无新 FK）。
    misconception_refs = spec.get("misconception_refs")
    if misconception_refs is not None and not isinstance(misconception_refs, dict):
        fail("g1", ValidationIssue("misconception_refs", "bad_refs",
                                   "misconception_refs must be an object"))

    # 门禁汇总：issue 代码直映射到门禁项（fail() 已同步置位，
    # 这里以映射为准统一结算，避免某一 issue 误伤无关门禁）。
    _CODE_TO_GATE = {
        "not_object": "g1", "bad_id": "g1", "duplicate_id": "g1",
        "verified_field_forbidden": "g1", "missing_field": "g1",
        "bad_points": "g1", "bad_design_note": "g1",
        "bad_figure_refs": "g1", "bad_object_key": "g1", "bad_refs": "g1",
        "bad_ku_id": "g2", "ku_existence_unchecked": "g2",
        "ku_not_found": "g2",
        "bad_options": "g3", "bad_option_count": "g3",
        "bad_answer_index": "g3", "answer_index_out_of_range": "g3",
        "bad_predict": "g3",
        "misconception_equals_answer": "g4", "misconception_unchecked": "g4",
        "caveat_too_short": "g5",
        "unknown_model": "g6", "bad_parameters": "g6", "bind_failed": "g6",
        "expected_required": "g6", "expected_too_few": "g6",
        "bad_entry": "g6", "bad_actions": "g6", "bad_expected": "g6",
        "model_rejected": "g6", "unknown_readout": "g6",
        "bad_expected_number": "g6", "readout_not_number": "g6",
        "expectation_mismatch": "g6", "no_reset_case": "g6",
        "no_transition_case": "g6", "stochastic_not_reproducible": "g6",
        "stochastic_no_sample": "g6", "bad_model_ref": "g6",
        "reset_not_restored": "g7", "state_mutated": "g7",
        "bad_view": "g7", "view_state_leak": "g7",
        "untagged_number": "g8",
        "bad_renderer_hint": "g9",
        "not_bilingual": "g10", "missing_language": "g10",
        "bad_language": "g10",
    }
    for issue in issues:
        gate = _CODE_TO_GATE.get(issue.code)
        if gate is not None:
            gates[gate] = False

    passed = not issues
    return ValidationResult(passed=passed, issues=issues, notes=notes, gates=gates)


def spec_provenance(spec: Mapping, textbook_id: str | None = None) -> dict:
    """规格的来源标注（复用 provenance.py 的档位与引用形态）。

    锚定 KU/教材的部分为 MATERIAL；config 与模型参数中的数值按其
    三标签原样列出，示意参数（illustrative）单独列出以便前端明示。
    """
    sources = [SourceRef(kind="ku", ref=str(spec.get("ku_id", "")))]
    if textbook_id:
        sources.append(SourceRef(kind="textbook", ref=textbook_id))
    number_kinds: dict[str, str] = {}

    def _walk(obj: object, path: str) -> None:
        if _is_tagged_number_dict(obj):
            try:
                number_kinds[path] = TaggedNumber.from_dict(obj).kind.value
            except (TypeError, ValueError):
                pass
            return
        if isinstance(obj, dict):
            for key, val in obj.items():
                if key in _STRUCTURAL_NUMBER_KEYS or key == "actions":
                    continue
                _walk(val, f"{path}.{key}" if path else key)
        elif isinstance(obj, list):
            for i, val in enumerate(obj):
                _walk(val, f"{path}[{i}]")

    _walk(spec.get("config", {}), "config")
    model_ref = spec.get("model_ref")
    if isinstance(model_ref, dict):
        _walk(model_ref.get("parameters", {}), "model_ref.parameters")
    return {
        "label": ProvenanceLabel.MATERIAL.value,
        "sources": [asdict(s) for s in sources],
        "number_kinds": number_kinds,
        "illustrative": sorted(
            p for p, k in number_kinds.items() if k == NumberKind.ILLUSTRATIVE.value
        ),
    }
