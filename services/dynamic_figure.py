"""轻量参数滑块动态图（GeoGebra 方法的 Mneme 3O 重做）。

GeoGebra（geogebra.org/calculator）是交互动态图引擎：拖滑块改参数，
图形实时联动。Mneme 的 teachable-figures 只有静态图规格，这是真缺口。
本模块干净重做一个轻量版：参数滑块 + 表达式读数 + SVG/Canvas 参数图
规格，纳入教学图规格体系；**未复制 GeoGebra 代码、素材或界面**，
GeoGebra 本站只作人工验算/外跳链接（见 geogebra_reference 字段），
不嵌入、不批量搬素材。

许可（GeoGebra 三层，2025-11 更新页）：
- 源码 EUPL v1.2；安装器/Web 服务/素材为 GeoGebra 自有非商用许可
  （署名 "Made with GeoGebra®" + 版权声明 + 链接），整体产品只限非商用；
- 语言文件/文档/UI 图片与网站内容 CC BY-NC-SA 4.0；
- 商用须另签许可。Mneme 按 Soffy 定调不商用，与之相容；一旦收费或
  作商业获客，须先签 GeoGebra 商用许可。

规格：参数（滑块）+ 读数（表达式）+ 视图（SVG/Canvas 画布声明）。
读数表达式走本模块自写的安全求值器（只认已声明参数名、常量与白名单
函数），不用 eval。门禁 d1–d8 全过才可用；期望读数在默认参数下逐条
复算，滑块两端须有限（不出现除零/溢出）。与 teachable-figures 的
关系：本模块是动态图规格层，静态图仍走 services.teaching_figure；
同一份参数+读数 feeding 图、读数、讲解（与真值模型同一份派生结果
的纪律一致）。

本模块是纯函数，无 DB、无网络、无 LLM。零迁移：动态图规格走既有
JSONB/spec 契约层，不新增表。
"""

from __future__ import annotations

import math
import re
from typing import Any, Collection, Mapping

from services.citation_check import check_citations
from services.teaching_figure import (
    TaggedNumber,
    ValidationIssue,
    ValidationResult,
)

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RENDERERS = ("svg-2d", "canvas-2d")
_GEOGEBRA_PREFIX = "https://www.geogebra.org/"

_FUNCTIONS: dict[str, Any] = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "sqrt": math.sqrt,
    "abs": abs,
    "exp": math.exp,
    "log": math.log,
    "ln": math.log,
    "floor": math.floor,
    "ceil": math.ceil,
}
_CONSTANTS: dict[str, float] = {"pi": math.pi, "e": math.e}
_RESERVED = set(_FUNCTIONS) | set(_CONSTANTS)


class ExpressionError(ValueError):
    """表达式解析或求值失败（不是看似合理的结果，直接拒绝）。"""


# ── 安全表达式求值器（自写递归下降，不用 eval）───────────────────────


def _tokenize(expr: str) -> list[tuple[str, Any]]:
    tokens: list[tuple[str, Any]] = []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch.isspace():
            i += 1
        elif ch.isdigit() or (ch == "." and i + 1 < len(expr) and expr[i + 1].isdigit()):
            match = re.match(r"\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?", expr[i:])
            assert match is not None  # noqa: S101 - 正则已保证匹配
            tokens.append(("num", float(match.group(0))))
            i += match.end()
        elif ch.isalpha() or ch == "_":
            match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", expr[i:])
            assert match is not None  # noqa: S101 - 正则已保证匹配
            tokens.append(("name", match.group(0)))
            i += match.end()
        elif ch in "+-*/^(),":
            tokens.append(("op", ch))
            i += 1
        else:
            raise ExpressionError(f"unexpected character {ch!r} in expression")
    tokens.append(("end", None))
    return tokens


class _Parser:
    """加减 < 乘除 < 幂（右结合）< 一元负 < 原子（数/变量/函数调用/括号）。"""

    def __init__(self, tokens: list[tuple[str, Any]]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> tuple[str, Any]:
        return self.tokens[self.pos]

    def take(self) -> tuple[str, Any]:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def parse(self) -> tuple:
        node = self._additive()
        if self.peek()[0] != "end":
            raise ExpressionError(f"trailing tokens after expression: {self.peek()!r}")
        return node

    def _additive(self) -> tuple:
        node = self._multiplicative()
        while self.peek() == ("op", "+") or self.peek() == ("op", "-"):
            op = self.take()[1]
            node = ("bin", op, node, self._multiplicative())
        return node

    def _multiplicative(self) -> tuple:
        node = self._power()
        while self.peek() == ("op", "*") or self.peek() == ("op", "/"):
            op = self.take()[1]
            node = ("bin", op, node, self._power())
        return node

    def _power(self) -> tuple:
        node = self._unary()
        if self.peek() == ("op", "^"):
            self.take()
            node = ("bin", "^", node, self._power())
        return node

    def _unary(self) -> tuple:
        if self.peek() == ("op", "-"):
            self.take()
            return ("neg", self._unary())
        if self.peek() == ("op", "+"):
            self.take()
            return self._unary()
        return self._primary()

    def _primary(self) -> tuple:
        kind, value = self.take()
        if kind == "num":
            return ("num", value)
        if kind == "name":
            if self.peek() == ("op", "("):
                self.take()
                args = [self._additive()]
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self._additive())
                if self.take() != ("op", ")"):
                    raise ExpressionError("missing closing parenthesis in function call")
                return ("call", value, tuple(args))
            return ("var", value)
        if (kind, value) == ("op", "("):
            node = self._additive()
            if self.take() != ("op", ")"):
                raise ExpressionError("missing closing parenthesis")
            return node
        raise ExpressionError(f"unexpected token {(kind, value)!r}")


def _ast_names(node: tuple) -> set[str]:
    kind = node[0]
    if kind == "num":
        return set()
    if kind == "var":
        return {node[1]}
    if kind == "neg":
        return _ast_names(node[1])
    if kind == "bin":
        return _ast_names(node[2]) | _ast_names(node[3])
    if kind == "call":
        names = {node[1]}
        for arg in node[2]:
            names |= _ast_names(arg)
        return names
    raise ExpressionError(f"unknown AST node {kind!r}")


def _ast_eval(node: tuple, env: Mapping[str, float]) -> float:
    kind = node[0]
    if kind == "num":
        return float(node[1])
    if kind == "var":
        name = node[1]
        if name in _CONSTANTS:
            return _CONSTANTS[name]
        if name not in env:
            raise ExpressionError(f"unknown variable {name!r}")
        return float(env[name])
    if kind == "neg":
        return -_ast_eval(node[1], env)
    if kind == "bin":
        _, op, left, right = node
        a = _ast_eval(left, env)
        b = _ast_eval(right, env)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            if b == 0:
                raise ExpressionError("division by zero")
            return a / b
        if op == "^":
            try:
                return a**b
            except (OverflowError, ValueError) as exc:
                raise ExpressionError(f"invalid power: {exc}") from exc
        raise ExpressionError(f"unknown operator {op!r}")
    if kind == "call":
        _, name, args = node
        fn = _FUNCTIONS.get(name)
        if fn is None:
            raise ExpressionError(f"unknown function {name!r}")
        values = [_ast_eval(arg, env) for arg in args]
        try:
            result = fn(*values)
        except (ValueError, OverflowError) as exc:
            raise ExpressionError(f"function {name} failed: {exc}") from exc
        if isinstance(result, bool) or not isinstance(result, (int, float)):
            raise ExpressionError(f"function {name} returned a non-number")
        return float(result)
    raise ExpressionError(f"unknown AST node {kind!r}")


def parse_expression(expr: str) -> tuple:
    """解析表达式为 AST；非法字符/结构直接抛 ExpressionError。"""
    if not isinstance(expr, str) or not expr.strip():
        raise ExpressionError("expression must be a non-empty string")
    return _Parser(_tokenize(expr)).parse()


def validate_expression(expr: object, param_names: Collection[str]) -> list[str]:
    """表达式静态检查：返回未知标识符列表（空即合法）。

    合法名字 = 已声明参数名 + 常量 pi/e + 白名单函数名（只许以调用形态出现）。
    """
    if not isinstance(expr, str):
        return ["expression must be a string"]
    try:
        tree = parse_expression(expr)
    except ExpressionError as exc:
        return [str(exc)]
    problems: list[str] = []
    for name in sorted(_ast_names(tree)):
        if name in param_names or name in _CONSTANTS or name in _FUNCTIONS:
            continue
        problems.append(f"unknown identifier {name!r}")
    return problems


def evaluate_expression(expr: str, values: Mapping[str, float]) -> float:
    """求值；结果须有限，否则抛 ExpressionError（不返回 inf/nan）。"""
    result = _ast_eval(parse_expression(expr), values)
    if not math.isfinite(result):
        raise ExpressionError("expression evaluated to a non-finite number")
    return result


# ── 动态图规格与验证门 ─────────────────────────────────────────────────


def _bilingual_text(
    value: object, field_name: str, issues: list[ValidationIssue]
) -> dict[str, str] | None:
    if not isinstance(value, dict):
        issues.append(
            ValidationIssue(field_name, "not_bilingual",
                            f"{field_name} must be an object with zh and en text")
        )
        return None
    ok = True
    for lang in ("zh", "en"):
        text = value.get(lang)
        if not isinstance(text, str) or not text.strip():
            issues.append(
                ValidationIssue(field_name, "missing_language",
                                f"{field_name}.{lang} must be a non-empty string")
            )
            ok = False
    return {"zh": value["zh"], "en": value["en"]} if ok else None


def _tagged(raw: object) -> TaggedNumber | None:
    try:
        return TaggedNumber.from_dict(raw)
    except (TypeError, ValueError):
        return None


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _param_bounds(spec: Mapping[str, Any]) -> dict[str, dict[str, float]] | None:
    """从已验规格取各参数的 min/max/default（门禁内部用，调用前须先过 d3）。"""
    bounds: dict[str, dict[str, float]] = {}
    for param in spec.get("parameters", []):
        if not isinstance(param, dict):
            return None
        name = param.get("name")
        parsed = {
            key: _tagged(param.get(key))
            for key in ("min", "max", "default")
        }
        if not isinstance(name, str) or any(v is None for v in parsed.values()):
            return None
        bounds[name] = {key: float(tagged.value)  # type: ignore[union-attr]
                        for key, tagged in parsed.items()}
    return bounds


def evaluate_dynamic_figure(
    spec: Mapping[str, Any],
    overrides: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """给定滑块值求读数；越界值 clamp（记入 clamped，不编造）。

    返回 {"parameters": {...}, "readouts": {...}, "clamped": [...]}。
    表达式非法/求值失败抛 ExpressionError；规格形态不对抛 ValueError。
    """
    bounds = _param_bounds(spec)
    if bounds is None:
        raise ValueError("spec parameters are malformed")
    values: dict[str, float] = {}
    clamped: list[str] = []
    for name, bound in bounds.items():
        value = bound["default"]
        if overrides is not None and name in overrides:
            raw = overrides[name]
            if not _is_number(raw):
                raise ValueError(f"override for {name!r} must be numeric")
            value = float(raw)
            if value < bound["min"] or value > bound["max"]:
                clamped.append(name)
                value = min(bound["max"], max(bound["min"], value))
        values[name] = value
    readouts: dict[str, float] = {}
    for readout in spec.get("readouts", []):
        if not isinstance(readout, dict):
            raise ValueError("readout must be an object")
        readouts[readout["name"]] = evaluate_expression(
            readout["expression"], values)
    return {"parameters": values, "readouts": readouts, "clamped": clamped}


def slider_sweep(spec: Mapping[str, Any]) -> dict[str, dict[str, dict[str, float]]]:
    """逐参数扫 min/default/max（其余取默认），返回各档读数表。"""
    bounds = _param_bounds(spec)
    if bounds is None:
        raise ValueError("spec parameters are malformed")
    sweep: dict[str, dict[str, dict[str, float]]] = {}
    for name, bound in bounds.items():
        sweep[name] = {}
        for level in ("min", "default", "max"):
            result = evaluate_dynamic_figure(spec, {name: bound[level]})
            sweep[name][level] = result["readouts"]
    return sweep


def verify_dynamic_figure(
    spec: object,
    *,
    known_ku_ids: Collection[str] | None = None,
    known_textbook_ids: Collection[str] | None = None,
) -> ValidationResult:
    """动态图验证门 d1–d8，全过才可用。"""
    issues: list[ValidationIssue] = []
    notes: list[str] = []
    gates: dict[str, bool] = {f"d{i}": True for i in range(1, 9)}

    def fail(gate: str, issue: ValidationIssue) -> None:
        gates[gate] = False
        issues.append(issue)

    if not isinstance(spec, dict):
        fail("d1", ValidationIssue("$", "not_object", "spec must be an object"))
        return ValidationResult(False, issues, notes, gates)

    # d1：schema 合法、id 形态、必填齐全；verified 字段门禁自管。
    spec_id = spec.get("id")
    if not isinstance(spec_id, str) or not _ID_RE.match(spec_id):
        fail("d1", ValidationIssue("id", "bad_id",
                                   "id must be a slug: [a-z0-9][a-z0-9_-]{0,99}"))
    if "verified" in spec:
        fail("d1", ValidationIssue("verified", "verified_field_forbidden",
                                   "verified is set by the server-side gate only"))
    for field_name in ("ku_id", "title", "language", "renderer",
                       "parameters", "readouts", "assertions"):
        if field_name not in spec:
            fail("d1", ValidationIssue(field_name, "missing_field",
                                       f"missing required field {field_name!r}"))
    title = _bilingual_text(spec.get("title"), "title", issues)
    if title is None and "title" in spec:
        gates["d1"] = False
    language = spec.get("language")
    if "language" in spec and language not in ("zh", "en"):
        fail("d1", ValidationIssue("language", "bad_language",
                                   "language must be 'zh' or 'en'"))
    if spec.get("renderer") not in _RENDERERS:
        fail("d1", ValidationIssue("renderer", "bad_renderer",
                                   f"renderer must be one of {_RENDERERS}"))

    # d2：锚点 KU 真实存在（不传已知集即判未核验，fail-closed）。
    ku_id = spec.get("ku_id")
    if not isinstance(ku_id, str) or not ku_id.strip():
        fail("d2", ValidationIssue("ku_id", "bad_ku_id",
                                   "ku_id must be a non-empty string"))
    elif known_ku_ids is None:
        fail("d2", ValidationIssue("ku_id", "ku_existence_unchecked",
                                   "anchor existence was not checked"))
    elif ku_id not in known_ku_ids:
        fail("d2", ValidationIssue("ku_id", "ku_not_found",
                                   f"knowledge unit {ku_id!r} does not exist"))

    # d3：参数（滑块）——名唯一合法、三标签齐全、min<max、step>0、默认在界内。
    params = spec.get("parameters")
    param_names: set[str] = set()
    bounds: dict[str, dict[str, float]] = {}
    if not isinstance(params, list) or not params:
        fail("d3", ValidationIssue("parameters", "parameters_required",
                                   "parameters must be a non-empty list"))
        params = []
    for idx, param in enumerate(params):
        base = f"parameters[{idx}]"
        if not isinstance(param, dict):
            fail("d3", ValidationIssue(base, "bad_parameter",
                                       "parameter must be an object"))
            continue
        name = param.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            fail("d3", ValidationIssue(f"{base}.name", "bad_param_name",
                                       "parameter name must be an identifier"))
            continue
        if name in _RESERVED:
            fail("d3", ValidationIssue(f"{base}.name", "reserved_param_name",
                                       f"parameter name {name!r} is reserved"))
            continue
        if name in param_names:
            fail("d3", ValidationIssue(f"{base}.name", "duplicate_param_name",
                                       f"duplicate parameter name {name!r}"))
            continue
        param_names.add(name)
        parsed: dict[str, TaggedNumber | None] = {}
        for key in ("min", "max", "step", "default"):
            parsed[key] = _tagged(param.get(key))
            if parsed[key] is None:
                fail("d3", ValidationIssue(f"{base}.{key}", "bad_tagged_number",
                                           f"{key} must be a tagged number"))
        if any(v is None for v in parsed.values()):
            continue
        minimum = parsed["min"].value  # type: ignore[union-attr]
        maximum = parsed["max"].value  # type: ignore[union-attr]
        step = parsed["step"].value  # type: ignore[union-attr]
        default = parsed["default"].value  # type: ignore[union-attr]
        if not minimum < maximum:
            fail("d3", ValidationIssue(base, "bad_range",
                                       "min must be less than max"))
        if not step > 0:
            fail("d3", ValidationIssue(base, "bad_step",
                                       "step must be positive"))
        if not minimum <= default <= maximum:
            fail("d3", ValidationIssue(base, "default_out_of_range",
                                       "default must lie within [min, max]"))
        bounds[name] = {"min": minimum, "max": maximum, "default": default}

    # d4：读数表达式只认已声明参数名、常量与白名单函数。
    readouts = spec.get("readouts")
    if not isinstance(readouts, list) or not readouts:
        fail("d4", ValidationIssue("readouts", "readouts_required",
                                   "readouts must be a non-empty list"))
        readouts = []
    readout_names: set[str] = set()
    for idx, readout in enumerate(readouts):
        base = f"readouts[{idx}]"
        if not isinstance(readout, dict):
            fail("d4", ValidationIssue(base, "bad_readout", "readout must be an object"))
            continue
        name = readout.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            fail("d4", ValidationIssue(f"{base}.name", "bad_readout_name",
                                       "readout name must be an identifier"))
            continue
        if name in readout_names:
            fail("d4", ValidationIssue(f"{base}.name", "duplicate_readout_name",
                                       f"duplicate readout name {name!r}"))
        readout_names.add(name)
        if not isinstance(readout.get("label"), str) or not readout["label"].strip():
            fail("d4", ValidationIssue(f"{base}.label", "bad_label",
                                       "label must be a non-empty string"))
        for problem in validate_expression(readout.get("expression"), param_names):
            fail("d4", ValidationIssue(f"{base}.expression", "bad_expression", problem))

    # d5：期望读数在默认参数下逐条复算（容差内一致）。
    defaults = {name: bound["default"] for name, bound in bounds.items()}
    for idx, readout in enumerate(readouts):
        base = f"readouts[{idx}]"
        if not isinstance(readout, dict):
            continue
        expected = _tagged(readout.get("expected"))
        if expected is None:
            fail("d5", ValidationIssue(f"{base}.expected", "bad_expected",
                                       "expected must be a tagged number"))
            continue
        if expected.kind.value != "calculation":
            fail("d5", ValidationIssue(f"{base}.expected", "expected_not_calculation",
                                       "expected readout kind must be 'calculation'"))
        if not isinstance(readout.get("unit"), str):
            fail("d5", ValidationIssue(f"{base}.unit", "bad_unit",
                                       "unit must be a string"))
        elif readout["unit"] != expected.unit:
            fail("d5", ValidationIssue(f"{base}.unit", "unit_mismatch",
                                       "readout unit must match expected unit"))
        if not validate_expression(readout.get("expression"), param_names):
            try:
                got = evaluate_expression(readout["expression"], defaults)
            except ExpressionError as exc:
                fail("d5", ValidationIssue(f"{base}.expression", "evaluation_failed",
                                           f"readout could not be evaluated: {exc}"))
                continue
            tol = readout.get("tolerance", 1e-9)
            if not _is_number(tol):
                tol = 1e-9
            tol = float(tol)
            if abs(got - expected.value) > tol + tol * abs(expected.value):
                fail("d5", ValidationIssue(
                    f"{base}.expected", "expectation_mismatch",
                    f"expected {expected.value} {expected.unit}, got {got}"))

    # d6：确定性 + 滑块两端有限（默认、逐参数 min/max、全 min、全 max）。
    if bounds and not any(i.code in ("bad_expression", "evaluation_failed")
                          for i in issues):
        try:
            first = evaluate_dynamic_figure(spec)
            second = evaluate_dynamic_figure(spec)
            if first != second:
                fail("d6", ValidationIssue("evaluation", "not_deterministic",
                                           "same sliders must give same readouts"))
            sweep_points: list[dict[str, float]] = [{}]
            for name, bound in bounds.items():
                sweep_points.append({name: bound["min"]})
                sweep_points.append({name: bound["max"]})
            sweep_points.append({name: b["min"] for name, b in bounds.items()})
            sweep_points.append({name: b["max"] for name, b in bounds.items()})
            for point in sweep_points:
                evaluate_dynamic_figure(spec, point)
        except (ExpressionError, ValueError) as exc:
            fail("d6", ValidationIssue("evaluation", "extreme_not_finite",
                                       f"readouts must stay finite at slider extremes: {exc}"))

    # d7：视图与语义分离——view 键不得与参数名重叠。
    view = spec.get("view")
    if view is not None:
        if not isinstance(view, dict):
            fail("d7", ValidationIssue("view", "bad_view", "view must be an object"))
        elif set(view) & param_names:
            fail("d7", ValidationIssue("view", "view_state_leak",
                                       "view keys must not overlap parameter names"))
        else:
            viewport = view.get("viewport")
            if viewport is not None:
                if not isinstance(viewport, dict):
                    fail("d7", ValidationIssue("view.viewport", "bad_viewport",
                                               "viewport must be an object"))
                else:
                    for axis in ("width", "height"):
                        size = viewport.get(axis)
                        if not _is_number(size) or float(size) <= 0:
                            fail("d7", ValidationIssue(
                                f"view.viewport.{axis}", "bad_viewport_size",
                                "viewport width/height must be positive numbers"))

    # d8：出处断言过 citation_check；GeoGebra 引用只许是外跳链接。
    assertions = spec.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        fail("d8", ValidationIssue("assertions", "assertions_required",
                                   "assertions must be a non-empty list"))
    else:
        checked = check_citations(
            assertions,
            known_ku_ids=set(known_ku_ids) if known_ku_ids is not None else None,
            known_textbook_ids=(
                set(known_textbook_ids) if known_textbook_ids is not None else None
            ),
        )
        if not checked["passed"]:
            for segment in checked["segments"]:
                for item in segment["issues"]:
                    fail("d8", ValidationIssue(
                        f"assertions[{segment['index']}]", item["code"],
                        item["message"]))
    geogebra_ref = spec.get("geogebra_reference")
    if geogebra_ref is not None:
        if not isinstance(geogebra_ref, str) or not geogebra_ref.startswith(_GEOGEBRA_PREFIX):
            fail("d8", ValidationIssue("geogebra_reference", "bad_geogebra_reference",
                                       "geogebra_reference must be a geogebra.org URL"))
        else:
            notes.append("geogebra_reference is a manual-verification outlink only; "
                         "GeoGebra is not embedded")

    _CODE_TO_GATE = {
        "not_object": "d1", "bad_id": "d1", "verified_field_forbidden": "d1",
        "missing_field": "d1", "not_bilingual": "d1", "missing_language": "d1",
        "bad_language": "d1", "bad_renderer": "d1",
        "bad_ku_id": "d2", "ku_existence_unchecked": "d2", "ku_not_found": "d2",
        "parameters_required": "d3", "bad_parameter": "d3", "bad_param_name": "d3",
        "reserved_param_name": "d3", "duplicate_param_name": "d3",
        "bad_tagged_number": "d3", "bad_range": "d3", "bad_step": "d3",
        "default_out_of_range": "d3",
        "readouts_required": "d4", "bad_readout": "d4", "bad_readout_name": "d4",
        "duplicate_readout_name": "d4", "bad_label": "d4", "bad_expression": "d4",
        "bad_expected": "d5", "expected_not_calculation": "d5", "bad_unit": "d5",
        "unit_mismatch": "d5", "evaluation_failed": "d5",
        "expectation_mismatch": "d5",
        "not_deterministic": "d6", "extreme_not_finite": "d6",
        "bad_view": "d7", "view_state_leak": "d7", "bad_viewport": "d7",
        "bad_viewport_size": "d7",
        "assertions_required": "d8", "bad_geogebra_reference": "d8",
    }
    for issue in issues:
        gate = _CODE_TO_GATE.get(issue.code)
        if gate is not None:
            gates[gate] = False

    return ValidationResult(passed=not issues, issues=issues, notes=notes,
                            gates=gates)


def example_dynamic_figure() -> dict[str, Any]:
    """合成演示动态图：抛物线 y=a·x²+b，三滑块（a/b/x），读数 y。"""
    return {
        "id": "demo-parabola-sliders",
        "ku_id": "demo-ku-quadratic",
        "title": {"zh": "抛物线参数滑块", "en": "Parabola parameter sliders"},
        "language": "zh",
        "renderer": "svg-2d",
        "parameters": [
            {
                "name": "a",
                "label": "二次项系数",
                "min": {"value": 0.5, "unit": "1", "kind": "illustrative",
                        "note": "为教学所选的滑块下限"},
                "max": {"value": 2.0, "unit": "1", "kind": "illustrative",
                        "note": "为教学所选的滑块上限"},
                "step": {"value": 0.1, "unit": "1", "kind": "illustrative",
                         "note": "为教学所选的滑块步长"},
                "default": {"value": 1.0, "unit": "1", "kind": "illustrative",
                            "note": "默认二次项系数"},
                "unit": "1",
            },
            {
                "name": "b",
                "label": "常数项",
                "min": {"value": -2.0, "unit": "1", "kind": "illustrative",
                        "note": "为教学所选的滑块下限"},
                "max": {"value": 2.0, "unit": "1", "kind": "illustrative",
                        "note": "为教学所选的滑块上限"},
                "step": {"value": 0.5, "unit": "1", "kind": "illustrative",
                         "note": "为教学所选的滑块步长"},
                "default": {"value": 0.0, "unit": "1", "kind": "illustrative",
                            "note": "默认常数项"},
                "unit": "1",
            },
            {
                "name": "x",
                "label": "自变量",
                "min": {"value": 0.0, "unit": "1", "kind": "illustrative",
                        "note": "为教学所选的滑块下限"},
                "max": {"value": 5.0, "unit": "1", "kind": "illustrative",
                        "note": "为教学所选的滑块上限"},
                "step": {"value": 0.5, "unit": "1", "kind": "illustrative",
                         "note": "为教学所选的滑块步长"},
                "default": {"value": 2.0, "unit": "1", "kind": "illustrative",
                            "note": "默认自变量取值"},
                "unit": "1",
            },
        ],
        "readouts": [
            {
                "name": "y",
                "label": "函数值",
                "expression": "a*x^2+b",
                "unit": "1",
                "expected": {"value": 4.0, "unit": "1", "kind": "calculation",
                             "note": "y=a·x²+b，a=1、x=2、b=0 时 y=4"},
            },
        ],
        "view": {"viewport": {"width": 640, "height": 480}},
        "assertions": [
            {
                "text": "二次函数 y=ax²+b 的图象为抛物线",
                "refs": [{"kind": "ku", "id": "demo-ku-quadratic"}],
            },
        ],
        "geogebra_reference": "https://www.geogebra.org/calculator",
    }


__all__ = [
    "ExpressionError",
    "evaluate_dynamic_figure",
    "evaluate_expression",
    "example_dynamic_figure",
    "parse_expression",
    "slider_sweep",
    "validate_expression",
    "verify_dynamic_figure",
]
