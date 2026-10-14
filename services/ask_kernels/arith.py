"""数与式的计算：有理数/分数/小数/百分数混合运算、乘方与负指数、科学记数法、二次根式、特殊角三角函数。

两条独立的计算路径互相验证：
- 精确值：sympy（沙箱解析）；
- 分步：自写的 Fraction AST 求值器（只认 + - * / ** 与 abs，逐个运算记步骤）；
- 校验：独立的浮点求值器（math 模块）与精确值比对。
"""

from __future__ import annotations

import ast
import math
import re
from fractions import Fraction
from typing import Any, Optional

from services.ask_kernels.core import KernelSolution, basic_normalize, fmt_num
from services.ask_kernels.sym import fmt, letters_of, math_normalize, parse, segments, value_str

# ── 学生写法 → 可 ast 解析的 Python（数字保持字面量） ─────────────────────────


def _plain_python(expr: str) -> str:
    e = expr.replace(" ", "")
    e = e.replace("sqrt", "§").replace("abs", "¤").replace("pi", "π").replace("cbrt", "¢")
    e = e.replace("sin", "ś").replace("cos", "ć").replace("tan", "ţ")
    e = re.sub(r"(\d|π|\))(?=[π(§¤¢śćţ])", r"\1*", e)
    e = re.sub(r"\)(?=\d)", ")*", e)
    e = re.sub(r"π(?=\d)", "π*", e)
    e = e.replace("^", "**")
    for a, b in (("§", "sqrt"), ("¤", "abs"), ("π", "pi"), ("¢", "cbrt"), ("ś", "sin"), ("ć", "cos"), ("ţ", "tan")):
        e = e.replace(a, b)
    return e


class _NotRational(Exception):
    pass


_OPS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "×", ast.Div: "÷", ast.Pow: "^"}


def fraction_eval(expr: str) -> tuple[Fraction, list[str]]:
    """只含有理运算的式子 → (精确值, 逐步运算记录)。遇到根号/π/字母抛 _NotRational。"""
    tree = ast.parse(_plain_python(expr), mode="eval")
    steps: list[str] = []
    use_dec = "." in expr

    def _fr(v: Fraction) -> str:
        s = fmt_num(v, max_dec=4) if use_dec else (f"{v.numerator}/{v.denominator}" if v.denominator != 1 else str(v.numerator))
        return f"({s})" if v < 0 else s

    def _res(v: Fraction) -> str:
        return fmt_num(v, max_dec=4) if use_dec else (f"{v.numerator}/{v.denominator}" if v.denominator != 1 else str(v.numerator))

    def is_lit(n: ast.AST) -> bool:
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            n = n.operand
        return isinstance(n, ast.Constant) and isinstance(n.value, int)

    def lit(n: ast.AST) -> int:
        if isinstance(n, ast.UnaryOp):
            return -int(n.operand.value)  # type: ignore[attr-defined]
        return int(n.value)  # type: ignore[attr-defined]

    def ev(n: ast.AST) -> Fraction:
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return Fraction(str(n.value))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            if isinstance(n.op, ast.USub) and isinstance(n.operand, ast.BinOp) and isinstance(n.operand.op, ast.Pow):
                steps.append(f"-({_res(v)}) = {_res(-v)}（注意：负号不参与乘方）")
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "abs" and len(n.args) == 1:
            v = ev(n.args[0])
            r = abs(v)
            steps.append(f"|{_res(v)}| = {_res(r)}")
            return r
        if (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div) and is_lit(n.left) and is_lit(n.right)
                and not use_dec and lit(n.right) != 0):
            return Fraction(lit(n.left), lit(n.right))  # 分数字面量
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            a, b = ev(n.left), ev(n.right)
            op = _OPS[type(n.op)]
            if isinstance(n.op, ast.Add):
                r = a + b
            elif isinstance(n.op, ast.Sub):
                r = a - b
            elif isinstance(n.op, ast.Mult):
                r = a * b
            elif isinstance(n.op, ast.Div):
                if b == 0:
                    raise ZeroDivisionError
                r = a / b
            else:
                if b.denominator != 1 or abs(b) > 64:
                    raise _NotRational
                if a == 0 and b < 0:
                    raise ZeroDivisionError
                r = a ** int(b)
            steps.append(f"{_fr(a)} {op} {_fr(b)} = {_res(r)}")
            return r
        raise _NotRational

    return ev(tree), steps


_SAFE_FUN: dict[str, Any] = {"sqrt": math.sqrt, "abs": abs, "sin": math.sin, "cos": math.cos, "tan": math.tan,
             "cbrt": lambda v: math.copysign(abs(v) ** (1 / 3), v)}


def float_eval(expr: str, env: Optional[dict[str, float]] = None) -> float:
    """独立的浮点求值器（校验用）：支持 + - * / ** sqrt abs sin cos tan pi 与给定变量。"""
    tree = ast.parse(_plain_python(expr), mode="eval")
    env = env or {}

    def ev(n: ast.AST) -> float:
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.Name):
            if n.id == "pi":
                return math.pi
            if n.id in env:
                return env[n.id]
            raise ValueError(n.id)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _SAFE_FUN and len(n.args) == 1:
            return float(_SAFE_FUN[n.func.id](ev(n.args[0])))
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Add):
                return a + b
            if isinstance(n.op, ast.Sub):
                return a - b
            if isinstance(n.op, ast.Mult):
                return a * b
            if isinstance(n.op, ast.Div):
                return a / b
            if isinstance(n.op, ast.Pow):
                if abs(b) > 64:
                    raise ValueError("pow")
                return float(a**b)
        raise ValueError("unsupported")

    return ev(tree)


# ── 科学记数法 ───────────────────────────────────────────────────────────────

_CN_UNIT = {"万": 10**4, "亿": 10**8, "千": 10**3, "百万": 10**6, "千万": 10**7, "万亿": 10**12}


def sci_parts(v: Fraction) -> tuple[Fraction, int]:
    if v == 0:
        return Fraction(0), 0
    n = 0
    a = abs(v)
    while a >= 10:
        a /= 10
        n += 1
    while a < 1:
        a *= 10
        n -= 1
    return (a if v > 0 else -a), n


def sci_str(v: Fraction) -> str:
    a, n = sci_parts(v)
    return f"{fmt_num(a, max_dec=8)}×10^{n}" if n >= 0 else f"{fmt_num(a, max_dec=8)}×10^({n})"


def solve_sci(text: str) -> Optional[KernelSolution]:
    t = basic_normalize(text)
    if "科学记数法" not in t and "科学计数法" not in t:
        return None
    t = re.sub(r"[a-z]\s*[×x*]\s*10\s*\^\s*n|1\s*≤\s*\|?a\|?\s*<\s*10", " ", t)
    ask_n = bool(re.search(r"(?<![a-z])n\s*(?:的值|=\s*\?|等于多少|是多少)|写出\s*n", t))
    ask_a = bool(re.search(r"(?<![a-z])a\s*(?:的值|=\s*\?|等于多少|是多少)|写出\s*a(?![a-z])", t))
    t2 = re.sub(r"\d{4}\s*年", "", t)
    ms = list(re.finditer(r"(-?\d+(?:\.\d+)?)\s*(万亿|千万|百万|万|亿)?", t2))
    with_unit = [m for m in ms if m.group(2)]
    ms = with_unit or ms
    if re.search(r"[×*]\s*10\s*\^", t) or len(ms) != 1:
        return None  # 含算式的交给算术内核
    m = ms[0]
    v = Fraction(m.group(1)) * (_CN_UNIT.get(m.group(2) or "", 1))
    if v == 0:
        return None
    a, n = sci_parts(v)
    s = sci_str(v)
    steps = [f"原数：{m.group(0)}" + (f" = {fmt_num(v, max_dec=10)}" if m.group(2) else "")]
    if n >= 0:
        steps.append(f"把小数点向左移动 {n} 位得到 1≤|a|<10 的数 a = {fmt_num(a, max_dec=8)}")
    else:
        steps.append(f"把小数点向右移动 {-n} 位得到 a = {fmt_num(a, max_dec=8)}，指数为负")
    steps.append(f"所以 {fmt_num(v, max_dec=10)} = {s}")
    check = a * Fraction(10) ** n == v
    if ask_n or ask_a:
        steps.append(f"所以 {'n = ' + str(n) if ask_n else 'a = ' + fmt_num(a, max_dec=8)}")
        return KernelSolution(
            kernel="arith.sci_notation", answer=(f"n = {n}" if ask_n else f"a = {fmt_num(a, max_dec=8)}"), steps=steps,
            hint="科学记数法写成 a×10ⁿ，其中 1≤|a|<10；小数点移动了几位，n 的绝对值就是几（原数小于 1 时 n 为负）。",
            explanation="科学记数法。", answer_value=str(n) if ask_n else fmt_num(a, max_dec=8), answer_kind="num",
            verified=bool(check), check="a×10ⁿ 还原等于原数",
        )
    return KernelSolution(
        kernel="arith.sci_notation",
        answer=s,
        steps=steps,
        hint="科学记数法写成 a×10ⁿ，其中 1≤|a|<10；小数点移动了几位，n 的绝对值就是几。",
        explanation="科学记数法：a×10ⁿ（1≤|a|<10，n 为整数）。",
        answer_value=fmt_num(v, max_dec=12),
        answer_kind="num",
        verified=bool(check),
        check="a×10ⁿ 还原等于原数",
    )


# ── 数值计算主内核 ───────────────────────────────────────────────────────────


def _pick_numeric_segment(s: str) -> Optional[str]:
    for seg in segments(s):
        expr = seg.split("=", 1)[0].strip().rstrip("?").strip()
        rhs = seg.split("=", 1)[1].strip() if "=" in seg else ""
        if rhs and rhs not in {"?", ""}:
            continue
        if letters_of(expr) or re.search(r"[<>≤≥≠]", expr):
            continue
        if not re.search(r"[+\-*/^]|abs|sin|cos|tan", expr.lstrip("-")) and not re.fullmatch(r"-?sqrt\(\d+\)", expr):
            continue
        if not re.search(r"\d", expr):
            continue
        return expr
    return None


def solve_arithmetic(text: str) -> Optional[KernelSolution]:
    import sympy as sp

    raw = basic_normalize(text)
    s = math_normalize(text)
    expr = _pick_numeric_segment(s)
    if expr is None:
        return None
    # 题面别处还有别的式子/字母未用上（比如“已知 x=2，求…”）→ 不是纯计算题
    if re.search(r"已知|其中|当\s*[a-z]\s*=|若|方程|不等式|函数|比较|哪个大|大小|科学记数法表示.{0,8}n", raw):
        return None
    if re.fullmatch(r"-?sqrt\(\d+\)", expr) and not re.search(r"化简|最简", raw):
        return None
    val = parse(expr)
    if not getattr(val, "is_number", False) or val.has(sp.zoo, sp.nan, sp.oo):
        return None
    val = sp.nsimplify(val) if isinstance(val, sp.Float) else val
    exact = val if val.is_Rational else sp.radsimp(sp.simplify(val))
    if isinstance(exact, sp.Add) and not exact.is_Rational:
        tog = sp.together(exact)
        if len(sp.sstr(tog)) <= len(sp.sstr(exact)) + 2:
            exact = tog
    if not exact.is_real:
        return None
    try:
        fv = float_eval(expr)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    if not math.isfinite(fv) or abs(float(exact) - fv) > 1e-6 * max(1.0, abs(fv)):
        return None
    steps: list[str] = []
    disp = expr.replace("*", "×").replace("sqrt", "√").replace("pi", "π")
    steps.append(f"原式 = {disp}")
    rational_steps: Optional[list[str]] = None
    try:
        fval, rational_steps = fraction_eval(expr)
        if Fraction(int(exact.p), int(exact.q)) != fval:  # type: ignore[union-attr]
            return None
    except (_NotRational, AttributeError, ZeroDivisionError, SyntaxError, TypeError):
        rational_steps = None
    if rational_steps:
        order = []
        if "(" in expr:
            order.append("先算括号里面的")
        if "^" in expr:
            order.append("再算乘方")
        if re.search(r"[*/]", expr):
            order.append("然后算乘除")
        if re.search(r"(?<=[0-9)])\s*[+\-]", expr):
            order.append("最后算加减")
        if order:
            steps.append("运算顺序：" + "，".join(order))
        for st in rational_steps[:10]:
            steps.append(st)
        if len(rational_steps) > 10:
            steps.append("……（按同样的顺序继续计算）")
        kernel = "arith.rational"
        hint = "按运算顺序来：有括号先算括号，再算乘方，然后乘除，最后加减；分数加减先通分。"
        expl = "有理数混合运算：严格按运算顺序，一步一步算。"
    else:
        kernel = "arith.radical" if "sqrt" in expr else ("arith.trig" if re.search(r"sin|cos|tan", expr) else "arith.real")
        if "sqrt" in expr:
            steps.append("先把每个二次根式化成最简二次根式（把被开方数里的完全平方因数开出来）")
            simp = [f"√{m} = {fmt(sp.sqrt(int(m)))}" for m in re.findall(r"sqrt\((\d+)\)", expr)
                    if fmt(sp.sqrt(int(m))) != f"√{m}"]
            steps.extend(simp[:6])
            if re.search(r"/\s*\(?[^()]*sqrt", expr):
                steps.append("分母含根号的，分子分母同乘分母的有理化因式，使分母有理化")
            steps.append("再合并同类二次根式（被开方数相同的才能合并），乘除按 √a·√b = √(ab) 计算")
            hint = "先把根式化简（开出完全平方因数），再合并同类二次根式；分母有根号要有理化。"
            expl = "二次根式的化简与运算。"
        elif re.search(r"sin|cos|tan", expr):
            vals = []
            for fn, deg in re.findall(r"(sin|cos|tan)\(pi\*(\d+)/180\)", expr):
                v = getattr(sp, fn)(sp.pi * int(deg) / 180)
                vals.append(f"{fn}{deg}° = {fmt(v)}")
            if vals:
                steps.append("代入特殊角的三角函数值：" + "，".join(vals))
            hint = "记住 30°、45°、60° 的正弦、余弦、正切值，代入后按实数运算。"
            expl = "特殊角三角函数值的计算。"
        else:
            hint = "按运算顺序计算，注意 π 等无理数保留符号。"
            expl = "实数运算。"
    ans = fmt(exact)
    approx = ""
    if not exact.is_Rational:
        approx = f"（≈ {float(exact):.4g}）"
    elif not exact.is_Integer and int(exact.q) > 1:
        dec = fmt_num(Fraction(int(exact.p), int(exact.q)), max_dec=4)
        if "/" not in dec:
            approx = f"（= {dec}）"
    steps.append(f"结果 = {ans}{approx}")
    if re.search(r"科学记数法", raw) and exact.is_Rational:
        sv = sci_str(Fraction(int(exact.p), int(exact.q)))
        steps.append(f"用科学记数法表示：{sv}")
        ans = sv
    return KernelSolution(
        kernel=kernel,
        answer=ans,
        steps=steps,
        hint=hint,
        explanation=expl,
        answer_value=value_str(exact),
        answer_kind="num",
        verified=True,
        check="精确值与独立浮点计算一致" + ("，分步有理运算一致" if rational_steps else ""),
    )


def solve_compare(text: str) -> Optional[KernelSolution]:
    """比较两个实数的大小（√7 与 2.6、-3/4 与 -0.7……）。"""
    import sympy as sp

    raw = basic_normalize(text)
    if not re.search(r"比较|哪个大|哪个小|较大|较小|大小", raw):
        return None
    s = math_normalize(text)
    m = re.search(r"([-+0-9a-z*/^().]+)\s*(?:与|和|,|、)\s*([-+0-9a-z*/^().]+)", s.replace(" ", ""))
    if not m:
        return None
    a_s, b_s = m.group(1).strip("(),"), m.group(2).strip("(),")
    try:
        a, b = parse(a_s), parse(b_s)
    except ValueError:
        return None
    if not (getattr(a, "is_number", False) and getattr(b, "is_number", False)) or letters_of(a_s + b_s):
        return None
    fa, fb = float(a), float(b)
    if abs(fa - fb) < 1e-12:
        return None
    big, small = (a, b) if fa > fb else (b, a)
    steps = [f"比较 {fmt(a)} 与 {fmt(b)}"]
    if "sqrt" in a_s + b_s:
        steps.append(f"两数都为正时可以比较平方：({fmt(a)})² = {fmt(sp.expand(a**2))}，({fmt(b)})² = {fmt(sp.expand(b**2))}" if fa > 0 and fb > 0 else
                     f"{fmt(a)} ≈ {fa:.4g}，{fmt(b)} ≈ {fb:.4g}")
    else:
        steps.append(f"{fmt(a)} = {fa:.6g}，{fmt(b)} = {fb:.6g}" + ("（两个负数比较，绝对值大的反而小）" if fa < 0 and fb < 0 else ""))
    want_small = bool(re.search(r"较小|哪个小|更小", raw))
    res = small if want_small else big
    steps.append(f"所以 {fmt(big)} > {fmt(small)}")
    return KernelSolution(
        kernel="arith.compare", answer=f"{fmt(big)} > {fmt(small)}" + (f"，较小的是 {fmt(small)}" if want_small else f"，较大的是 {fmt(big)}"),
        steps=steps, hint="比较实数大小：都化成小数比较，或者都为正数时比较它们的平方；负数比较绝对值大的反而小。",
        explanation="实数的大小比较。", answer_value=value_str(res), answer_kind="num", check="数值比较",
    )


__all__ = ["float_eval", "fraction_eval", "sci_str", "solve_arithmetic", "solve_compare", "solve_sci"]
