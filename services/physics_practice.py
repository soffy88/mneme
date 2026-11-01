"""计算题纪律：题由模型参数化生成，答案由模型算出、另一算法重算对上。

Atlas of Physics 的 practice 纪律（方法，非代码/题目）：练习的每个数
都由模型算出，checks 再用另一算法重算 keyed 答案，干扰项须与真值拉开
2% 以上。本模块把这条纪律写成 Mneme 的纯函数门禁：

- 生成：build_practice_item 绑定参数、跑模型 derive，把算出的答案
  写进题项——答案永不手写。
- 验证：verify_practice_item 重算答案（模型的独立重算路径），核对
  单位、题干占位符、假设文本点名忽略项；选择题另验 keyed 选项与
  干扰项间距。任一门不过，题项整体 unverified。
- 题干占位符 {name} 只许引用模型参数名或模型读数名：题干不得含
  模型未声明的量。

本模块是纯函数，无 DB、无网络、无 LLM 调用，可脱服务直测。
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence

from services.teaching_figure import (
    ImpossibleStateError,
    TaggedNumber,
    ValidationIssue,
    ValidationResult,
    find_untagged_numbers,
)
from services.physics_models import (
    PHYSICS_MODEL_REGISTRY,
    PhysicsTruthModel,
)

__all__ = [
    "build_practice_item",
    "verify_practice_item",
]

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_BILINGUAL_FIELDS = ("stem", "assumptions")


def _bilingual_text(
    value: object, field_name: str, issues: list[ValidationIssue]
) -> dict[str, str] | None:
    if not isinstance(value, dict):
        issues.append(
            ValidationIssue(
                field_name,
                "not_bilingual",
                f"{field_name} must be an object with zh and en text",
            )
        )
        return None
    zh, en = value.get("zh"), value.get("en")
    ok = True
    for lang, text in (("zh", zh), ("en", en)):
        if not isinstance(text, str) or not text.strip():
            issues.append(
                ValidationIssue(
                    field_name,
                    "missing_language",
                    f"{field_name}.{lang} must be a non-empty string",
                )
            )
            ok = False
    return {"zh": zh, "en": en} if ok else None


def _bind_model(
    model: PhysicsTruthModel, parameters: object
) -> tuple[dict | None, list[str]]:
    if not isinstance(parameters, dict):
        return None, ["parameters must be an object"]
    bound, issues, _clamped = model.bind_parameters(parameters)
    return (bound if not issues else None), issues


def _state_after(
    model: PhysicsTruthModel,
    bound: Mapping,
    actions: Sequence[dict],
) -> dict:
    state = model.initial_state(bound)
    for action in actions:
        if not isinstance(action, dict):
            raise ImpossibleStateError("action must be an object")
        state = model.apply_action(state, action)
    return state


def build_practice_item(
    *,
    item_id: str,
    model_name: str,
    parameters: dict,
    stem: dict[str, str],
    answer_readout: str,
    tolerance: float,
    assumptions: dict[str, str],
    language: str = "zh",
    kind: str = "numeric",
    choices: list[dict] | None = None,
    answer_index: int | None = None,
    actions: Sequence[dict] = (),
    ku_id: str | None = None,
) -> dict:
    """参数化生成题项：答案由模型 derive 算出并写进题项，永不手写。

    choices（选择题）由作者提供 4 个带标签数值 + answer_index；
    keyed 选项与干扰项间距由 verify_practice_item 门禁核验。
    本函数只负责“算出答案并组装”，不负责“判对”——判对永远是
    verify_practice_item 的事。
    """
    model = PHYSICS_MODEL_REGISTRY[model_name]
    bound, bind_issues = _bind_model(model, parameters)
    if bind_issues:
        raise ValueError(f"parameter binding failed: {bind_issues}")
    assert bound is not None
    state = _state_after(model, bound, actions)
    derived = model.derive(state)
    value = derived.get(answer_readout)
    if not isinstance(value, TaggedNumber):
        raise ValueError(f"model has no numeric readout {answer_readout!r}")
    item: dict = {
        "id": item_id,
        "model": model_name,
        "parameters": parameters,
        "actions": list(actions),
        "stem": stem,
        "kind": kind,
        "answer": {
            "readout": answer_readout,
            "value": value.to_dict(),
            "tolerance": tolerance,
        },
        "assumptions": assumptions,
        "language": language,
    }
    if ku_id is not None:
        item["ku_id"] = ku_id
    if kind == "choice":
        if choices is None:
            raise ValueError("choice items require choices")
        item["choices"] = choices
        item["answer_index"] = answer_index
    return item


def verify_practice_item(
    item: object,
    *,
    known_ku_ids: object | None = None,
) -> ValidationResult:
    """验证门：q1–q6 全过才 verified，失败逐条列原因。

    q1 schema（id 唯一、必填齐全、verified 字段禁入、双语齐全、
    kind 合法）；q2 模型已知、参数绑定成功、答案读数存在且单位
    一致、容差为正、锚点 KU（若给出）真实存在；q3 答案由模型
    算出且独立重算对上；q4 题干占位符只引用模型参数或读数；
    q5 假设文本点名模型的全部忽略项；q6 选择题 keyed 选项与
    干扰项间距（keyed 对上真值、干扰项拉开 2% 以上）。
    """
    issues: list[ValidationIssue] = []
    notes: list[str] = []
    gates: dict[str, bool] = {f"q{i}": True for i in range(1, 7)}

    def fail(gate: str, issue: ValidationIssue) -> None:
        gates[gate] = False
        issues.append(issue)

    if not isinstance(item, dict):
        fail("q1", ValidationIssue("$", "not_object", "item must be an object"))
        return ValidationResult(False, issues, notes, gates)

    # q1：schema。
    item_id = item.get("id")
    if not isinstance(item_id, str) or not _ID_RE.match(item_id):
        fail(
            "q1",
            ValidationIssue(
                "id", "bad_id", "id must be a slug: [a-z0-9][a-z0-9_-]{0,99}"
            ),
        )
    if "verified" in item:
        fail(
            "q1",
            ValidationIssue(
                "verified",
                "verified_field_forbidden",
                "verified is set by the server-side gate only",
            ),
        )
    for field_name in (
        "model",
        "parameters",
        "stem",
        "kind",
        "answer",
        "assumptions",
        "language",
    ):
        if field_name not in item:
            fail(
                "q1",
                ValidationIssue(
                    field_name, "missing_field", f"missing required field {field_name!r}"
                ),
            )
    texts: dict[str, dict[str, str] | None] = {}
    for field_name in _BILINGUAL_FIELDS:
        if field_name in item:
            texts[field_name] = _bilingual_text(item[field_name], field_name, issues)
    if any(v is None for v in texts.values()):
        gates["q1"] = False
    if item.get("language") not in ("zh", "en"):
        fail(
            "q1",
            ValidationIssue(
                "language", "bad_language", "language must be 'zh' or 'en'"
            ),
        )
    kind = item.get("kind")
    if kind not in ("numeric", "choice"):
        fail(
            "q1",
            ValidationIssue("kind", "bad_kind", "kind must be 'numeric' or 'choice'"),
        )

    # q2：模型、参数、答案读数、单位、容差、锚点。
    model: PhysicsTruthModel | None = None
    bound: dict | None = None
    derived: dict | None = None
    model_name = item.get("model")
    if isinstance(model_name, str):
        model = PHYSICS_MODEL_REGISTRY.get(model_name)
        if model is None:
            fail(
                "q2",
                ValidationIssue(
                    "model", "unknown_model", f"unknown physics model: {model_name!r}"
                ),
            )
    elif "model" in item:
        fail("q2", ValidationIssue("model", "bad_model", "model must be a string"))
    answer = item.get("answer")
    tolerance: float | None = None
    if model is not None:
        bound, bind_issues = _bind_model(model, item.get("parameters"))
        for msg in bind_issues:
            fail("q2", ValidationIssue("parameters", "bind_failed", msg))
        if bound is not None:
            actions = item.get("actions", [])
            if not isinstance(actions, list) or not all(
                isinstance(a, dict) for a in actions
            ):
                fail(
                    "q2",
                    ValidationIssue(
                        "actions",
                        "bad_actions",
                        "actions must be a list of action objects",
                    ),
                )
                actions = []
            try:
                state = _state_after(model, bound, actions)
                derived = model.derive(state)
            except ImpossibleStateError as exc:
                fail(
                    "q2",
                    ValidationIssue(
                        "model", "model_rejected", f"model rejected the case: {exc}"
                    ),
                )
    if isinstance(answer, dict):
        readout = answer.get("readout")
        raw_tol = answer.get("tolerance")
        if isinstance(raw_tol, bool) or not isinstance(raw_tol, (int, float)):
            fail(
                "q2",
                ValidationIssue(
                    "answer.tolerance",
                    "bad_tolerance",
                    "tolerance must be a positive number",
                ),
            )
        elif raw_tol <= 0:
            fail(
                "q2",
                ValidationIssue(
                    "answer.tolerance",
                    "bad_tolerance",
                    "tolerance must be a positive number",
                ),
            )
        else:
            tolerance = float(raw_tol)
        if derived is not None:
            if not isinstance(readout, str) or readout not in derived:
                fail(
                    "q2",
                    ValidationIssue(
                        "answer.readout",
                        "unknown_readout",
                        f"model has no readout {readout!r}",
                    ),
                )
            else:
                value = derived[readout]
                if not isinstance(value, TaggedNumber):
                    fail(
                        "q2",
                        ValidationIssue(
                            "answer.readout",
                            "readout_not_number",
                            f"readout {readout!r} is not a tagged number",
                        ),
                    )
                else:
                    stored = answer.get("value")
                    try:
                        stored_tn = (
                            TaggedNumber.from_dict(stored)
                            if isinstance(stored, dict)
                            else None
                        )
                    except (TypeError, ValueError):
                        stored_tn = None
                    if stored_tn is None:
                        fail(
                            "q2",
                            ValidationIssue(
                                "answer.value",
                                "bad_answer_value",
                                "answer.value must be a tagged number",
                            ),
                        )
                    elif stored_tn.unit != value.unit:
                        fail(
                            "q2",
                            ValidationIssue(
                                "answer.value",
                                "unit_mismatch",
                                f"answer unit {stored_tn.unit!r} != model unit "
                                f"{value.unit!r}",
                            ),
                        )
    elif "answer" in item:
        fail("q2", ValidationIssue("answer", "bad_answer", "answer must be an object"))

    ku_id = item.get("ku_id")
    if isinstance(ku_id, str) and ku_id.strip():
        if known_ku_ids is None:
            fail(
                "q2",
                ValidationIssue(
                    "ku_id",
                    "ku_existence_unchecked",
                    "anchor existence was not checked",
                ),
            )
        elif ku_id not in known_ku_ids:
            fail(
                "q2",
                ValidationIssue(
                    "ku_id", "ku_not_found", f"knowledge unit {ku_id!r} does not exist"
                ),
            )
    elif ku_id is not None and not isinstance(ku_id, str):
        fail("q2", ValidationIssue("ku_id", "bad_ku_id", "ku_id must be a string"))

    # q3：答案重算对上（独立路径），容差取题项 tolerance 与数值
    # 噪声下限的最大值——数值方法的舍入误差不得误杀好题。
    if (
        model is not None
        and bound is not None
        and derived is not None
        and isinstance(answer, dict)
        and tolerance is not None
    ):
        readout = answer.get("readout")
        stored = answer.get("value")
        if isinstance(readout, str) and isinstance(stored, dict):
            try:
                stored_value = float(stored.get("value"))
            except (TypeError, ValueError):
                stored_value = None
            if stored_value is not None:
                actions = item.get("actions", [])
                if not isinstance(actions, list):
                    actions = []
                try:
                    recomputed = model.recompute(readout, bound, actions)
                except (ImpossibleStateError, KeyError, ValueError) as exc:
                    fail(
                        "q3",
                        ValidationIssue(
                            "answer",
                            "recompute_failed",
                            f"independent recomputation failed: {exc}",
                        ),
                    )
                else:
                    derived_value = derived[readout].value
                    bar = max(tolerance, 1e-6 * max(1.0, abs(derived_value)))
                    if abs(stored_value - derived_value) > bar:
                        fail(
                            "q3",
                            ValidationIssue(
                                "answer",
                                "answer_mismatch",
                                f"stored answer {stored_value!r} != model value "
                                f"{derived_value!r} (bar {bar!r})",
                            ),
                        )
                    if abs(recomputed - derived_value) > bar:
                        fail(
                            "q3",
                            ValidationIssue(
                                "answer",
                                "recompute_mismatch",
                                f"recomputed {recomputed!r} != model value "
                                f"{derived_value!r} (bar {bar!r})",
                            ),
                        )

    # q4：题干占位符只引用模型参数名或读数名。
    stem = texts.get("stem")
    if stem is not None and model is not None and derived is not None:
        allowed = {p.name for p in model.parameters} | set(derived)
        for lang in ("zh", "en"):
            for name in _PLACEHOLDER_RE.findall(stem[lang]):
                if name not in allowed:
                    fail(
                        "q4",
                        ValidationIssue(
                            "stem",
                            "undeclared_placeholder",
                            f"stem.{lang} uses {{{name}}}, not a model parameter "
                            "or readout",
                        ),
                    )

    # q5：假设文本点名全部忽略项。
    assumptions = texts.get("assumptions")
    if assumptions is not None:
        for lang in ("zh", "en"):
            if len(assumptions[lang].strip()) < 8:
                fail(
                    "q5",
                    ValidationIssue(
                        "assumptions",
                        "assumptions_too_short",
                        f"assumptions.{lang} must state the idealizations",
                    ),
                )
        if model is not None:
            for term in model.ignored_terms():
                if term["zh"] not in assumptions["zh"]:
                    fail(
                        "q5",
                        ValidationIssue(
                            "assumptions",
                            "ignored_term_missing",
                            f"assumptions.zh must name the ignored item {term['zh']!r}",
                        ),
                    )
                if term["en"].lower() not in assumptions["en"].lower():
                    fail(
                        "q5",
                        ValidationIssue(
                            "assumptions",
                            "ignored_term_missing",
                            f"assumptions.en must name the ignored item {term['en']!r}",
                        ),
                    )

    # q6：选择题间距纪律。
    if kind == "choice":
        choices = item.get("choices")
        answer_index = item.get("answer_index")
        if not isinstance(choices, list) or len(choices) != 4:
            fail(
                "q6",
                ValidationIssue(
                    "choices", "bad_choices", "choice items need exactly 4 choices"
                ),
            )
        elif not isinstance(answer_index, int) or isinstance(answer_index, bool):
            fail(
                "q6",
                ValidationIssue(
                    "answer_index",
                    "bad_answer_index",
                    "answer_index must be an integer",
                ),
            )
        elif not 0 <= answer_index < 4:
            fail(
                "q6",
                ValidationIssue(
                    "answer_index",
                    "answer_index_out_of_range",
                    "answer_index must point at one choice",
                ),
            )
        else:
            tagged: list[TaggedNumber | None] = []
            for idx, raw in enumerate(choices):
                try:
                    tagged.append(
                        TaggedNumber.from_dict(raw) if isinstance(raw, dict) else None
                    )
                except (TypeError, ValueError):
                    tagged.append(None)
                if tagged[-1] is None:
                    fail(
                        "q6",
                        ValidationIssue(
                            f"choices[{idx}]",
                            "bad_choice",
                            "each choice must be a tagged number",
                        ),
                    )
            values = [t.value for t in tagged if t is not None]
            if len(values) == 4:
                if len(set(values)) != 4:
                    fail(
                        "q6",
                        ValidationIssue(
                            "choices", "duplicate_choices", "choices must be distinct"
                        ),
                    )
                if (
                    derived is not None
                    and isinstance(answer, dict)
                    and tolerance is not None
                ):
                    readout = answer.get("readout")
                    if isinstance(readout, str) and readout in derived:
                        want = derived[readout].value
                        bar = max(tolerance, 1e-6 * max(1.0, abs(want)))
                        keyed = values[answer_index]
                        if abs(keyed - want) > bar:
                            fail(
                                "q6",
                                ValidationIssue(
                                    "choices",
                                    "keyed_mismatch",
                                    f"keyed choice {keyed!r} != model value {want!r}",
                                ),
                            )
                        scale = max(abs(want), 1.0)
                        for idx, distractor in enumerate(values):
                            if idx != answer_index and abs(distractor - want) <= (
                                0.02 * scale
                            ):
                                fail(
                                    "q6",
                                    ValidationIssue(
                                        "choices",
                                        "distractor_too_close",
                                        f"choice {idx} ({distractor!r}) is within 2% "
                                        f"of the keyed value {want!r}",
                                    ),
                                )

    # q6 之外的数字三标签全覆盖（题项内一切裸数都须带标签）。
    for problem in find_untagged_numbers(item):
        fail("q1", ValidationIssue("numbers", "untagged_number", problem))

    _CODE_TO_GATE = {
        "not_object": "q1",
        "bad_id": "q1",
        "verified_field_forbidden": "q1",
        "missing_field": "q1",
        "not_bilingual": "q1",
        "missing_language": "q1",
        "bad_language": "q1",
        "bad_kind": "q1",
        "untagged_number": "q1",
        "unknown_model": "q2",
        "bad_model": "q2",
        "bind_failed": "q2",
        "bad_actions": "q2",
        "model_rejected": "q2",
        "bad_tolerance": "q2",
        "unknown_readout": "q2",
        "readout_not_number": "q2",
        "bad_answer_value": "q2",
        "unit_mismatch": "q2",
        "bad_answer": "q2",
        "bad_ku_id": "q2",
        "ku_existence_unchecked": "q2",
        "ku_not_found": "q2",
        "recompute_failed": "q3",
        "answer_mismatch": "q3",
        "recompute_mismatch": "q3",
        "undeclared_placeholder": "q4",
        "assumptions_too_short": "q5",
        "ignored_term_missing": "q5",
        "bad_choices": "q6",
        "bad_answer_index": "q6",
        "answer_index_out_of_range": "q6",
        "bad_choice": "q6",
        "duplicate_choices": "q6",
        "keyed_mismatch": "q6",
        "distractor_too_close": "q6",
    }
    for issue in issues:
        gate = _CODE_TO_GATE.get(issue.code)
        if gate is not None:
            gates[gate] = False

    passed = not issues
    return ValidationResult(passed=passed, issues=issues, notes=notes, gates=gates)
