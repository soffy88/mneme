"""
化学方程式配平确定性计算原语（oprim 层）
=========================================

化学式解析、组成矩阵、配平系数、守恒表、摩尔质量、LaTeX 排版与独立整数复核，
全部是确定性计算：配平由 sympy 精确有理数零空间得出，复核只用 Python 整数，
不依赖 LLM、不做心算。

3O 范式 oprim 约束：
- 每个公开函数是一次原子计算，公开函数之间互不调用（只共享 ``_`` 私有工具）
- 纯函数：无 IO、无全局状态、无随机；纯计算故为同步函数
- 签名：≤1 个核心位置参数，其余 keyword-only
- 输入输出类型显式（Pydantic 模型 / int / float / str）

安全：化学式只走手写的分词器 + 递归下降解析器（元素符号白名单、括号配对、
结晶水点、电荷后缀、长度 / 嵌套 / 计数上限），绝不对外部字符串调用
``eval`` / ``sympy.sympify``；sympy 只接收解析器产出的 Python 整数。

书写约定（ASCII，可混用 Unicode 下标 ₀–₉）：
- 下标直接跟数字：``Fe2O3``、``Ca(OH)2``、``K3[Fe(CN)6]``
- 结晶水用 ``·`` / ``•`` / ``.`` / ``*``，其后可带系数：``CuSO4·5H2O``
- 电荷用 ``^`` 后缀，数字在前或在后、可加花括号：``Fe^2+``、``MnO4^-``、``SO4^{2-}``

来源：配平思路（元素×物种矩阵 → sympy 零空间 → 最小正整数）派生自 wy51ai/edulab
``skills/edu-chem-reaction/lib/reaction_kernel.py``（``balanced_coefficients``、
``equation_latex``）与 ``lib/molecules.py``（commit
6a9c8766061ca7101d10bab6fe3af716ec47bb07，Apache-2.0，Copyright 2026 WY (@akokoi1)）。
已改写为 3O oprim 形态，并新增严格化学式解析、电荷守恒行、多解 / 非正系数拒绝、
教材原子量表与独立整数复核。
"""

from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import Literal

import sympy as sp
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ──────────────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────────────

MAX_FORMULA_LEN = 40
MAX_SPECIES_PER_SIDE = 6
MAX_NESTING = 3
MAX_SUBSCRIPT = 999
MAX_HYDRATE_COEF = 20
MAX_HYDRATE_PARTS = 3
MAX_ATOMS_PER_FORMULA = 500
MAX_CHARGE = 9
MAX_COEFFICIENT = 10_000
CHARGE_ROW = "charge"

# 全部 118 个真实元素符号（IUPAC）
ELEMENT_SYMBOLS: frozenset[str] = frozenset(
    """
    H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn
    Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce
    Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At
    Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn
    Nh Fl Mc Lv Ts Og
    """.split()
)

# 中国中学教材常用相对原子质量（人教版附录取值）。以字符串保存，用 Fraction 精确求和。
# fmt: off
ATOMIC_WEIGHTS: dict[str, str] = {
    "H": "1", "He": "4", "Li": "7", "Be": "9", "B": "11", "C": "12", "N": "14", "O": "16",
    "F": "19", "Ne": "20", "Na": "23", "Mg": "24", "Al": "27", "Si": "28", "P": "31",
    "S": "32", "Cl": "35.5", "Ar": "40", "K": "39", "Ca": "40", "Ti": "48", "Cr": "52",
    "Mn": "55", "Fe": "56", "Co": "59", "Ni": "59", "Cu": "64", "Zn": "65", "Br": "80",
    "Ag": "108", "Sn": "119", "I": "127", "Ba": "137", "Pt": "195", "Au": "197",
    "Hg": "201", "Pb": "207",
}
# fmt: on

_SUBSCRIPT_IN = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_CHARSET_RE = re.compile(r"^[A-Za-z0-9()\[\]·•.*^+\-{}]+$")
_CHARGE_RE = re.compile(r"^(?:([1-9]?)([+-])|([+-])([1-9]?))$")
_HYDRATE_SPLIT_RE = re.compile(r"[·•.*]")
_ARROW_RE = re.compile(r"\s*(?:->|→|⟶|=)\s*")
_SIDE_SPLIT_RE = re.compile(r"\s+\+\s+")


# ──────────────────────────────────────────────────────────────────────────────
# 类型
# ──────────────────────────────────────────────────────────────────────────────


def _precheck(value: str) -> str:
    v = value.strip().translate(_SUBSCRIPT_IN)
    if not v:
        raise ValueError("empty formula")
    if len(v) > MAX_FORMULA_LEN:
        raise ValueError(f"formula longer than {MAX_FORMULA_LEN} characters")
    if not _CHARSET_RE.match(v):
        raise ValueError(f"illegal characters in formula: {value!r}")
    return v


class ReactionSpec(BaseModel):
    """结构化反应：反应物与产物的化学式字符串（未配平）。

    这里只做长度与字符集预检；元素白名单与语法由 ``parse_formula`` 严格校验。
    """

    reactants: list[str] = Field(min_length=1, max_length=MAX_SPECIES_PER_SIDE)
    products: list[str] = Field(min_length=1, max_length=MAX_SPECIES_PER_SIDE)
    language: Literal["zh-CN"] = "zh-CN"

    model_config = ConfigDict(extra="forbid")

    @field_validator("reactants", "products")
    @classmethod
    def _formulas_ok(cls, v: list[str]) -> list[str]:
        return [_precheck(x) for x in v]

    @model_validator(mode="after")
    def _no_duplicates(self) -> ReactionSpec:
        all_species = self.reactants + self.products
        if len(set(all_species)) != len(all_species):
            raise ValueError("the same formula appears more than once in the reaction")
        return self

    @classmethod
    def from_equation(cls, equation: str) -> ReactionSpec:
        """``"Fe2O3 + CO -> Fe + CO2"`` → ReactionSpec。

        箭头可为 ``->`` / ``→`` / ``⟶`` / ``=``；物质之间用两侧带空格的 `` + `` 分隔
        （因此 ``H^+ + OH^-`` 中电荷的 ``+`` 不会被误拆）。
        """
        if not isinstance(equation, str) or len(equation) > 2 * MAX_SPECIES_PER_SIDE * (MAX_FORMULA_LEN + 3):
            raise ValueError("equation too long")
        sides = _ARROW_RE.split(equation.strip())
        if len(sides) != 2:
            raise ValueError("equation must contain exactly one arrow")
        left, right = (_SIDE_SPLIT_RE.split(s.strip()) for s in sides)
        return cls(reactants=left, products=right)


class ParsedFormula(BaseModel):
    """解析结果。``counts`` 按元素首次出现顺序排列。"""

    formula: str  # 规范写法，如 "CuSO4·5H2O"、"MnO4^-"、"Fe^2+"
    counts: dict[str, int]
    charge: int = 0

    model_config = ConfigDict(extra="forbid")


class CompositionMatrix(BaseModel):
    """组成矩阵：行 = 元素（可加一行电荷 ``CHARGE_ROW``），列 = 物种（反应物在前）。

    数值为各物种自身的原子数 / 电荷数（不带方向符号）。
    """

    rows: list[str]
    species: list[str]
    n_reactants: int
    matrix: list[list[int]]

    model_config = ConfigDict(extra="forbid")


class ConservationRow(BaseModel):
    """一行守恒检验：``row`` 为元素符号或 ``CHARGE_ROW``。"""

    row: str
    left: int
    right: int
    balanced: bool


class BalanceCheck(BaseModel):
    """独立整数复核结果。"""

    ok: bool
    problems: list[str]
    totals: dict[str, list[int]]  # row -> [left, right]


# ──────────────────────────────────────────────────────────────────────────────
# 私有工具（可被多个公开原语共享；公开原语之间不互相调用）
# ──────────────────────────────────────────────────────────────────────────────

# token: (kind, text)，kind ∈ el / sub / open / close / dot / coef
_Token = tuple[str, str]


class _Parser:
    """单个结晶水片段的递归下降解析器：``seq := group+``；
    ``group := ELEMENT count? | '(' seq ')' count? | '[' seq ']' count?``。"""

    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0
        self.tokens: list[_Token] = []

    def _count(self) -> int:
        j = self.i
        while j < len(self.s) and self.s[j].isdigit():
            j += 1
        if j == self.i:
            return 1
        digits = self.s[self.i : j]
        if digits[0] == "0" or int(digits) > MAX_SUBSCRIPT:
            raise ValueError(f"invalid subscript {digits!r}")
        self.i = j
        self.tokens.append(("sub", digits))
        return int(digits)

    def seq(self, depth: int, closer: str | None) -> dict[str, int]:
        if depth > MAX_NESTING:
            raise ValueError(f"brackets nested deeper than {MAX_NESTING}")
        counts: dict[str, int] = {}
        n_groups = 0
        while self.i < len(self.s):
            ch = self.s[self.i]
            if ch in ")]":
                if closer != ch:
                    raise ValueError(f"unbalanced bracket {ch!r}")
                break
            if ch in "([":
                want = ")" if ch == "(" else "]"
                self.tokens.append(("open", ch))
                self.i += 1
                inner = self.seq(depth + 1, want)
                if self.i >= len(self.s) or self.s[self.i] != want:
                    raise ValueError(f"missing closing {want!r}")
                self.tokens.append(("close", want))
                self.i += 1
                mult = self._count()
                for el, n in inner.items():
                    counts[el] = counts.get(el, 0) + n * mult
            elif ch.isupper():
                sym = ch
                if self.i + 1 < len(self.s) and self.s[self.i + 1].islower():
                    sym = self.s[self.i : self.i + 2]
                if sym not in ELEMENT_SYMBOLS:
                    raise ValueError(f"unknown element symbol {sym!r}")
                self.i += len(sym)
                self.tokens.append(("el", sym))
                n = self._count()
                counts[sym] = counts.get(sym, 0) + n
            else:
                raise ValueError(f"unexpected character {ch!r} in formula")
            n_groups += 1
        if n_groups == 0:
            raise ValueError("empty group in formula")
        if closer is None and self.i != len(self.s):
            raise ValueError("trailing characters in formula")
        return counts


def _parse(formula: str) -> tuple[dict[str, int], int, list[_Token], str]:
    """严格解析：返回 (元素计数, 电荷, 显示 token, 电荷后缀规范写法)。"""
    if not isinstance(formula, str):
        raise ValueError("formula must be a string")
    s = _precheck(formula)

    charge, charge_text = 0, ""
    if "^" in s:
        if s.count("^") != 1:
            raise ValueError("at most one charge suffix")
        s, raw = s.split("^")
        if raw.startswith("{") and raw.endswith("}"):
            raw = raw[1:-1]
        m = _CHARGE_RE.match(raw)
        if not m:
            raise ValueError(f"invalid charge suffix {raw!r}")
        mag = int(m.group(1) or m.group(4) or "1")
        sign = m.group(2) or m.group(3)
        if mag > MAX_CHARGE:
            raise ValueError("charge too large")
        charge = mag if sign == "+" else -mag
        charge_text = f"{mag if mag > 1 else ''}{sign}"
    if any(c in s for c in "+-{}^"):
        raise ValueError("charge must be written as a single '^' suffix, e.g. Fe^2+")
    if not s:
        raise ValueError("charge without formula body")

    parts = _HYDRATE_SPLIT_RE.split(s)
    if len(parts) > MAX_HYDRATE_PARTS:
        raise ValueError("too many hydrate parts")
    counts: dict[str, int] = {}
    tokens: list[_Token] = []
    for k, part in enumerate(parts):
        if not part:
            raise ValueError("empty hydrate part")
        mult = 1
        if k > 0:
            tokens.append(("dot", "·"))
            m = re.match(r"^(\d+)", part)
            if m:
                digits = m.group(1)
                if digits[0] == "0" or int(digits) > MAX_HYDRATE_COEF:
                    raise ValueError(f"invalid hydrate coefficient {digits!r}")
                mult = int(digits)
                tokens.append(("coef", digits))
                part = part[len(digits) :]
        elif part[0].isdigit():
            raise ValueError("leading coefficient is not allowed; coefficients are computed")
        p = _Parser(part)
        sub = p.seq(1, None)
        tokens.extend(p.tokens)
        for el, n in sub.items():
            counts[el] = counts.get(el, 0) + n * mult
    if sum(counts.values()) > MAX_ATOMS_PER_FORMULA:
        raise ValueError("formula has too many atoms")
    return counts, charge, tokens, charge_text


def _normalized(tokens: list[_Token], charge_text: str) -> str:
    body = "".join(t for _, t in tokens)
    return f"{body}^{charge_text}" if charge_text else body


def _latex_of(tokens: list[_Token], charge_text: str) -> str:
    out: list[str] = []
    for kind, text in tokens:
        if kind == "sub":
            out.append(f"_{{{text}}}")
        elif kind == "dot":
            out.append(r"\cdot ")
        elif kind == "open" and text == "[":
            out.append(r"\lbrack ")
        elif kind == "close" and text == "]":
            out.append(r"\rbrack ")
        else:
            out.append(text)
    tex = r"\mathrm{" + "".join(out) + "}"
    return f"{tex}^{{{charge_text}}}" if charge_text else tex


def _coef_term(coef: int, tex: str) -> str:
    return tex if coef == 1 else f"{coef}\\,{tex}"


# ──────────────────────────────────────────────────────────────────────────────
# 原语
# ──────────────────────────────────────────────────────────────────────────────


def parse_formula(formula: str) -> ParsedFormula:
    """严格解析一个化学式（分子 / 离子 / 结晶水合物）。非法输入一律 ``ValueError``。"""
    counts, charge, tokens, charge_text = _parse(formula)
    return ParsedFormula(formula=_normalized(tokens, charge_text), counts=counts, charge=charge)


def formula_latex(formula: str) -> str:
    """单个化学式 → 纯 LaTeX（``\\mathrm`` + 下标，无 ``\\ce``）。"""
    _, _, tokens, charge_text = _parse(formula)
    return _latex_of(tokens, charge_text)


def composition_matrix(species: list[ParsedFormula], *, n_reactants: int) -> CompositionMatrix:
    """元素（+电荷）× 物种 的组成矩阵。元素按首次出现顺序；任一物种带电时追加电荷行。"""
    if not 1 <= n_reactants < len(species):
        raise ValueError("need at least one reactant and one product")
    rows: list[str] = []
    for s in species:
        for el in s.counts:
            if el not in rows:
                rows.append(el)
    matrix = [[s.counts.get(el, 0) for s in species] for el in rows]
    if any(s.charge for s in species):
        rows.append(CHARGE_ROW)
        matrix.append([s.charge for s in species])
    return CompositionMatrix(rows=rows, species=[s.formula for s in species], n_reactants=n_reactants, matrix=matrix)


def balance_coefficients(matrix: CompositionMatrix) -> list[int]:
    """sympy 精确零空间 → 最小正整数化学计量数（与 ``matrix.species`` 顺序对应）。

    拒绝：元素只出现在一侧；零空间维数 0（无法配平）或 >1（多解）；出现非正系数。
    """
    n = matrix.n_reactants
    for name, row in zip(matrix.rows, matrix.matrix, strict=True):
        if name == CHARGE_ROW:
            continue
        if not any(row[:n]) or not any(row[n:]):
            side = "反应物" if any(row[:n]) else "产物"
            raise ValueError(f"无法配平：元素 {name} 只出现在{side}一侧，原子不守恒")
    signed = sp.Matrix([[sp.Integer(v if j < n else -v) for j, v in enumerate(row)] for row in matrix.matrix])
    basis = signed.nullspace()
    if len(basis) == 0:
        raise ValueError("无法配平：守恒方程组只有零解，所给物质不能构成守恒的反应")
    if len(basis) > 1:
        raise ValueError(
            f"多解：守恒方程组解空间维数为 {len(basis)}，系数不唯一（可能是几个独立反应叠加），无法确定唯一配平"
        )
    vec = [sp.Rational(v) for v in basis[0]]
    lcm = 1
    for v in vec:
        lcm = math.lcm(lcm, int(v.q))
    ints = [int(v * lcm) for v in vec]
    g = 0
    for v in ints:
        g = math.gcd(g, abs(v))
    ints = [v // g for v in ints]
    if all(v <= 0 for v in ints):
        ints = [-v for v in ints]
    if any(v <= 0 for v in ints):
        raise ValueError(f"无法配平：解出的系数 {ints} 含非正值，所给物质不能全部按所写方向参与反应")
    if max(ints) > MAX_COEFFICIENT:
        raise ValueError("无法配平：系数超出合理范围")
    return ints


def atom_conservation_table(matrix: CompositionMatrix, *, coefficients: list[int]) -> list[ConservationRow]:
    """按行统计方程左右两侧的原子总数（及电荷总数）。"""
    if len(coefficients) != len(matrix.species):
        raise ValueError("coefficient count does not match species count")
    n = matrix.n_reactants
    out: list[ConservationRow] = []
    for name, row in zip(matrix.rows, matrix.matrix, strict=True):
        left = sum(c * v for c, v in zip(coefficients[:n], row[:n], strict=True))
        right = sum(c * v for c, v in zip(coefficients[n:], row[n:], strict=True))
        out.append(ConservationRow(row=name, left=left, right=right, balanced=left == right))
    return out


def molar_mass(formula: ParsedFormula) -> float:
    """摩尔质量（g/mol），按教材相对原子质量表精确求和后保留 2 位小数。

    离子不计电子质量（与教材一致）。元素不在 ``ATOMIC_WEIGHTS`` 中时 ``ValueError``。
    """
    total = Fraction(0)
    for el, n in formula.counts.items():
        if el not in ATOMIC_WEIGHTS:
            raise ValueError(f"元素 {el} 不在中学常用相对原子质量表中")
        total += Fraction(ATOMIC_WEIGHTS[el]) * n
    hundredths = math.floor(total * 100 + Fraction(1, 2))  # 四舍五入到 0.01
    return hundredths / 100


def format_equation_latex(coefficients: list[int], *, reactants: list[str], products: list[str]) -> str:
    """配平后的方程式 → 纯 LaTeX（无 ``\\ce``），系数 1 省略，箭头 ``\\rightarrow``。"""
    species = list(reactants) + list(products)
    if len(coefficients) != len(species):
        raise ValueError("coefficient count does not match species count")
    if any(not isinstance(c, int) or isinstance(c, bool) or c <= 0 for c in coefficients):
        raise ValueError("coefficients must be positive integers")
    terms = []
    for c, f in zip(coefficients, species, strict=True):
        _, _, tokens, charge_text = _parse(f)
        terms.append(_coef_term(c, _latex_of(tokens, charge_text)))
    n = len(reactants)
    return " + ".join(terms[:n]) + r" \rightarrow " + " + ".join(terms[n:])


def numeric_balance_check(coefficients: list[int], *, reactants: list[str], products: list[str]) -> BalanceCheck:
    """独立整数复核：不用 sympy、不用组成矩阵，直接从化学式重新计数，
    检查每种元素与总电荷守恒、系数为正整数且互质（最简）。"""
    problems: list[str] = []
    species = list(reactants) + list(products)
    if len(coefficients) != len(species):
        return BalanceCheck(ok=False, problems=["coefficient count does not match species count"], totals={})
    for c in coefficients:
        if not isinstance(c, int) or isinstance(c, bool) or c <= 0:
            problems.append(f"non-positive or non-integer coefficient {c!r}")
    if problems:
        return BalanceCheck(ok=False, problems=problems, totals={})
    g = 0
    for c in coefficients:
        g = math.gcd(g, c)
    if g != 1:
        problems.append(f"coefficients share a common factor {g}")

    totals: dict[str, list[int]] = {}
    n = len(reactants)
    for idx, (c, f) in enumerate(zip(coefficients, species, strict=True)):
        side = 0 if idx < n else 1
        counts, charge, _, _ = _parse(f)
        for el, k in counts.items():
            totals.setdefault(el, [0, 0])[side] += c * k
        totals.setdefault(CHARGE_ROW, [0, 0])[side] += c * charge
    for name, (left, right) in totals.items():
        if left != right:
            problems.append(f"{name}: left {left} != right {right}")
    return BalanceCheck(ok=not problems, problems=problems, totals=totals)
