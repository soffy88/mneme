"""拍照问题目的确定性求解（不调用 LLM）。

把识别/输入的中文题面里的数学式子抠出来，用 sympy 精确求解，生成中文分步与提示：
- 一元一次 / 一元二次方程（含因式分解与求根公式两条路）
- 纯算术（四则、乘方、括号、分数）
化学方程式配平复用既有精确内核（services.chemical_equation_service.balance）。

安全：只把白名单字符（数字、单字母变量、运算符、括号、等号、小数点）转成 SymPy 语法后，
交给仓内统一沙箱 obase.sympy_runtime（AST 白名单 + 超时 + 内存上限）求值；
解析不了就返回 None，由调用方回落 LLM。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Optional

_FULL2HALF = str.maketrans(
    "０１２３４５６７８９＋－＝（）．，：／ｘｙ",
    "0123456789+-=().,:/xy",
)
_VARS = "xyzabmnt"
_SEG = re.compile(r"[0-9a-zA-Z+\-*/^().=\s?？]+")


@dataclass
class KernelSolution:
    kernel: str
    answer: str
    steps: list[str] = field(default_factory=list)
    hint: str = ""
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kernel": self.kernel,
            "answer": self.answer,
            "steps": self.steps,
            "hint": self.hint,
            "explanation": self.explanation,
        }


def normalize_math_text(text: str) -> str:
    """OCR/手输题面 → 便于抠式子的形式（全角转半角、乘除号、上标）。"""
    s = (text or "").translate(_FULL2HALF)
    s = s.replace("²", "^2").replace("³", "^3").replace("√", "sqrt")
    s = s.replace("÷", "/").replace("·", "*").replace("−", "-").replace("–", "-")
    # OCR 常把变量 x 认成乘号 ×/X：两侧都是数字/右括号才当乘号，否则当 x
    s = re.sub(r"(?<=[0-9)])\s*[×xX]\s*(?=[0-9(])", "*", s)
    s = s.replace("×", "x").replace("X", "x")
    return s


def _candidates(s: str) -> list[str]:
    out = []
    for m in _SEG.finditer(s):
        seg = m.group(0).strip(" .,:")
        seg = seg.replace("？", "?")
        if not re.search(r"\d", seg):
            continue
        if not re.search(r"[+\-*/^=]", seg):
            continue
        out.append(seg)
    out.sort(key=len, reverse=True)
    return out


def _fmt(expr: Any) -> str:
    import sympy as sp

    if isinstance(expr, sp.Rational) and not isinstance(expr, sp.Integer):
        return f"{expr.p}/{expr.q}"
    s = sp.sstr(expr)
    s = s.replace("**", "^")
    s = re.sub(r"(\d)\*([a-z(])", r"\1\2", s)
    s = s.replace(")*(", ")(")
    s = s.replace("sqrt", "√")
    return s


_RUNTIME: Any = None


def _runtime() -> Any:
    """仓内统一的 sympy 沙箱（obase.sympy_runtime：AST 白名单 + fork 超时 + 内存上限）。"""
    global _RUNTIME
    if _RUNTIME is None:
        from obase.sympy_runtime import SymPyRuntime

        _RUNTIME = SymPyRuntime()
    return _RUNTIME


def to_python_syntax(expr: str) -> str:
    """学生写法 → Python/SymPy 语法：补隐式乘号、^→**、整数/小数字面量转精确有理数。"""
    e = expr.replace(" ", "").replace("sqrt", "§")
    e = re.sub(r"(\d)([a-z(§])", r"\1*\2", e)
    e = re.sub(r"\)([0-9a-z(§])", r")*\1", e)
    e = re.sub(r"([a-z])(?=[a-z(§])", r"\1*", e)
    e = e.replace("^", "**")

    def _num(m: re.Match[str]) -> str:
        t = m.group(0)
        if "." in t:
            whole, frac = t.split(".", 1)
            return f"Rational({int(whole + frac)},{10 ** len(frac)})"
        return f"Integer({int(t)})"

    e = re.sub(r"\d+\.\d+|\d+", _num, e)
    return e.replace("§", "sqrt")


def _parse(expr: str, var_names: str) -> Any:
    if not re.fullmatch(r"[0-9a-z+\-*/^().\s]*", expr):
        raise ValueError("unsupported characters")
    if re.search(r"[a-z]{2,}", expr.replace("sqrt", "")):
        raise ValueError("multi-letter identifiers")
    if not expr.strip():
        raise ValueError("empty")
    res = _runtime().evaluate(
        to_python_syntax(expr),
        {v: v for v in var_names},
        timeout=2.0,
        simplify_result=False,
    )
    if not res.success:
        raise ValueError(res.error or "parse failed")
    return res.value


def _solve_equation(seg: str) -> Optional[KernelSolution]:
    import sympy as sp

    lhs_s, rhs_s = seg.split("=", 1)
    lhs_s, rhs_s = lhs_s.strip(), rhs_s.strip()
    letters = sorted(set(re.findall(r"[a-z]", (lhs_s + rhs_s).replace("sqrt", ""))))
    if len(letters) != 1 or letters[0] not in _VARS:
        return None
    v = letters[0]
    lhs, rhs = _parse(lhs_s, v), _parse(rhs_s, v)
    sym = sp.Symbol(v)
    poly_expr = sp.expand(lhs - rhs)
    try:
        poly = sp.Poly(poly_expr, sym)
    except sp.PolynomialError:
        return None
    deg = poly.degree()
    if deg < 1 or deg > 2:
        return None
    roots = sp.solve(sp.Eq(lhs, rhs), sym)
    eq_disp = f"{_fmt(lhs)} = {_fmt(rhs)}"
    if deg == 1:
        a, b = poly.all_coeffs()  # a*v + b = 0
        steps = [f"原方程：{eq_disp}"]
        rhs_const = -b
        steps.append(f"移项（含 {v} 的项放左边，常数放右边）：{_fmt(a * sym)} = {_fmt(rhs_const)}")
        if a != 1:
            a_disp = f"({_fmt(a)})" if a < 0 else _fmt(a)
            steps.append(f"两边同时除以 {a_disp}：{v} = {_fmt(rhs_const)} ÷ {a_disp}")
        root = roots[0] if roots else rhs_const / a
        steps.append(f"所以 {v} = {_fmt(root)}")
        try:
            check_val = sp.simplify(lhs.subs(sym, root))
            steps.append(f"检验：把 {v} = {_fmt(root)} 代入左边得 {_fmt(check_val)}，与右边 {_fmt(rhs.subs(sym, root))} 相等 ✓")
        except Exception:  # noqa: BLE001
            pass
        return KernelSolution(
            kernel="algebra.linear",
            answer=f"{v} = {_fmt(root)}",
            steps=steps,
            hint=f"把含 {v} 的项留在等号左边、常数项移到右边（移项要变号），再把 {v} 的系数化成 1。",
            explanation="一元一次方程：移项、合并同类项、系数化为 1，最后代回检验。",
        )
    a, b, c = poly.all_coeffs()
    steps = [f"原方程：{eq_disp}", f"整理成一般形式：{_fmt(poly_expr)} = 0"]
    factored = sp.factor(poly_expr)
    real_roots = [r for r in roots if r.is_real]
    if factored != poly_expr and isinstance(factored, sp.Mul):
        steps.append(f"因式分解：{_fmt(factored)} = 0")
        steps.append("两个因式的积为 0，至少有一个因式为 0")
    else:
        disc = sp.simplify(b**2 - 4 * a * c)
        steps.append(f"a = {_fmt(a)}，b = {_fmt(b)}，c = {_fmt(c)}")
        steps.append(f"判别式 Δ = b² - 4ac = {_fmt(disc)}")
        if disc < 0:
            steps.append("Δ < 0，方程没有实数根")
            return KernelSolution(
                kernel="algebra.quadratic",
                answer="无实数根",
                steps=steps,
                hint="先把方程整理成 ax²+bx+c=0，再算判别式 Δ = b²-4ac 判断根的情况。",
                explanation="一元二次方程：Δ<0 时没有实数根。",
            )
        steps.append(f"用求根公式 {v} = (-b ± √Δ) / (2a)")
    if not real_roots:
        return None
    uniq = []
    for r in real_roots:
        if r not in uniq:
            uniq.append(r)
    if len(uniq) == 1:
        ans = f"{v}₁ = {v}₂ = {_fmt(uniq[0])}"
    else:
        ans = "，".join(f"{v}{'₁₂'[i]} = {_fmt(r)}" for i, r in enumerate(uniq[:2]))
    steps.append(f"所以 {ans}")
    return KernelSolution(
        kernel="algebra.quadratic",
        answer=ans,
        steps=steps,
        hint="先整理成 ax²+bx+c=0 的形式，试试因式分解；分解不了再用求根公式（先算 Δ = b²-4ac）。",
        explanation="一元二次方程：优先因式分解，其次求根公式。",
    )


def _solve_arithmetic(seg: str) -> Optional[KernelSolution]:
    import sympy as sp

    expr_s = seg.split("=", 1)[0].strip()
    if re.search(r"[a-z]", expr_s.replace("sqrt", "")):
        return None
    if not re.search(r"[+\-*/^]", expr_s.lstrip("-")):
        return None
    val = _parse(expr_s, "")
    if not getattr(val, "is_number", False):
        return None
    val = sp.nsimplify(val) if isinstance(val, sp.Float) else val
    disp = expr_s.replace("*", "×").replace("/", "÷")
    steps = [f"原式 = {disp}"]
    if "(" in expr_s:
        steps.append("先算括号里面的")
    if "^" in expr_s:
        steps.append("再算乘方（注意负数的乘方：(-2)^2 = 4，而 -2^2 = -4）")
    if re.search(r"[*/]", expr_s):
        steps.append("然后算乘除")
    if re.search(r"(?<=[0-9)])\s*[+\-]", expr_s):
        steps.append("最后算加减")
    ans = _fmt(val)
    if isinstance(val, sp.Rational) and not isinstance(val, sp.Integer):
        ans = f"{ans}（≈ {float(val):.4g}）"
    steps.append(f"结果 = {ans}")
    return KernelSolution(
        kernel="arithmetic",
        answer=ans,
        steps=steps,
        hint="按运算顺序来：有括号先算括号，再算乘方，然后乘除，最后加减。",
        explanation="有理数混合运算：严格按运算顺序，一步一步算。",
    )


def solve_math_text(text: str) -> Optional[KernelSolution]:
    """从题面里抠式子并精确求解；不适用返回 None（同步，CPU 很轻）。"""
    s = normalize_math_text(text)
    for seg in _candidates(s)[:4]:
        seg = seg.replace("?", "").strip()
        try:
            if "=" in seg and seg.split("=", 1)[1].strip():
                sol = _solve_equation(seg)
            else:
                sol = _solve_arithmetic(seg)
        except Exception:  # noqa: BLE001 — 解析失败就试下一个候选，最后回落 LLM
            sol = None
        if sol is not None:
            return sol
    return None


_CHEM = re.compile(
    r"((?:\d*[A-Z][a-z]?\d*(?:\([A-Za-z0-9]+\)\d*)*\s*\+\s*)*\d*[A-Z][a-z]?[A-Za-z0-9()]*)\s*"
    r"(?:=|→|->|⟶|——|==|＝)\s*"
    r"((?:\d*[A-Z][a-z]?[A-Za-z0-9()]*\s*\+\s*)*\d*[A-Z][a-z]?[A-Za-z0-9()]*)"
)
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def find_chemical_equation(text: str) -> Optional[str]:
    s = (text or "").translate(_SUBSCRIPTS).translate(_FULL2HALF)
    m = _CHEM.search(s)
    if not m:
        return None
    left, right = m.group(1), m.group(2)
    # 至少一侧有两种物质、且含化学式特征（大写字母开头）
    if "+" not in left and "+" not in right:
        return None
    strip_coef = lambda side: [re.sub(r"^\d+", "", p.strip()) for p in side.split("+") if p.strip()]  # noqa: E731
    return " + ".join(strip_coef(left)) + " = " + " + ".join(strip_coef(right))


async def solve_chemistry_text(text: str) -> Optional[KernelSolution]:
    eq = find_chemical_equation(text)
    if not eq:
        return None
    try:
        from oprim.chemical_equation import ReactionSpec

        from services.chemical_equation_service import balance

        spec = ReactionSpec.from_equation(eq)
        sol = await balance(spec)
    except Exception:  # noqa: BLE001 — 不是合法方程式就交回 LLM
        return None
    steps_raw = sol.get("steps") or []
    steps: list[str] = []
    for st in steps_raw:
        if isinstance(st, dict):
            steps.append(str(st.get("text") or st.get("description") or st.get("title") or "").strip())
        else:
            steps.append(str(st))
    steps = [s for s in steps if s][:8]
    answer = str(sol.get("equation_text") or "")
    if not answer:
        return None
    steps.append(f"配平结果：{answer}")
    return KernelSolution(
        kernel="chemistry.balance",
        answer=answer,
        steps=steps,
        hint="配平的关键：反应前后每种元素的原子个数相等。可以从只出现在一种反应物和一种生成物里的元素开始配。",
        explanation="化学方程式配平（原子守恒），系数取最小正整数。",
    )


async def solve_exact(text: str, subject: Optional[str]) -> Optional[KernelSolution]:
    """按学科路由到精确内核；都不适用返回 None。数学在线程里跑，3 秒超时。"""
    if subject in (None, "", "chemistry", "化学"):
        chem = await solve_chemistry_text(text)
        if chem is not None:
            return chem
    if subject in (None, "", "math", "数学", "physics", "物理"):
        try:
            return await asyncio.wait_for(asyncio.to_thread(solve_math_text, text), timeout=3.0)
        except Exception:  # noqa: BLE001 — 超时/异常 → 回落 LLM
            return None
    return None


__all__ = [
    "KernelSolution",
    "find_chemical_equation",
    "normalize_math_text",
    "solve_exact",
    "solve_math_text",
]
