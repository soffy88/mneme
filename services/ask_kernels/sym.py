"""数学题面 → SymPy 对象（只经仓内沙箱 obase.sympy_runtime 解析外部输入）。

- ``math_normalize``：在 core.basic_normalize 之上做数学专用替换（√、π、|…|、×/÷、x2→x^2、
  特殊角三角函数、带分数、百分号）。
- ``segments``：从中文题面里抠出连续的数学式子片段。
- ``parse``：学生写法 → Python 语法 → 沙箱求值（AST 白名单 + fork 超时）。
- ``fmt``：SymPy 对象 → 学生习惯的写法（x^2、√3、分数）。
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from services.ask_kernels.core import basic_normalize

_RUNTIME: Any = None


def runtime() -> Any:
    global _RUNTIME
    if _RUNTIME is None:
        from obase.sympy_runtime import SymPyRuntime

        _RUNTIME = SymPyRuntime()
    return _RUNTIME


_TRIG = re.compile(r"(sin|cos|tan|cot)\s*(\^\s*2)?\s*∠?\s*(\d{1,3})\s*°")


def math_normalize(text: str) -> str:
    s = basic_normalize(text)
    s = s.replace("π", "pi").replace("⁄", "/")
    # 绝对值 |…| → abs(…)（不嵌套，按出现顺序配对）
    if s.count("|") >= 2 and s.count("|") % 2 == 0:
        parts = s.split("|")
        out = parts[0]
        for i, p in enumerate(parts[1:]):
            out += ("abs(" if i % 2 == 0 else ")") + p
        s = out
    s = re.sub(r"(\d+)\s*又\s*(\d+)\s*/\s*(\d+)", r"(\1+\2/\3)", s)
    # 带分数印刷体“2 3/4”（整数 + 空格 + 真分数）
    s = re.sub(r"(?<![\d./^])(\d+)\s+(\d+)\s*/\s*(\d+)(?![\d.])",
               lambda m: f"({m.group(1)}+{m.group(2)}/{m.group(3)})" if int(m.group(2)) < int(m.group(3)) else m.group(0), s)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", s)
    # 特殊角：sin30° → sin(pi*30/180)；tan²60° → tan(pi*60/180)^2
    s = _TRIG.sub(lambda m: (f"(1/tan(pi*{m.group(3)}/180))" if m.group(1) == "cot" else f"{m.group(1)}(pi*{m.group(3)}/180)")
                  + ("^2" if m.group(2) else ""), s)
    # √：√(…) / √12 / √x / ³√8
    s = re.sub(r"\^3\s*√\s*(\d+(?:\.\d+)?)", r"cbrt(\1)", s)
    s = re.sub(r"√\s*\(", "sqrt(", s)
    s = re.sub(r"√\s*(\d+(?:\.\d+)?|[a-z])", r"sqrt(\1)", s)
    # 乘除号：两侧是操作数才当乘号；OCR 把变量 x 认成 ×/X 的情况
    s = re.sub(r"(?<=[0-9)a-z])\s*[×✕]\s*(?=[0-9(a-z√s])", "*", s)
    s = re.sub(r"(?<=[0-9)])\s*[xX]\s*(?=[0-9(])", "*", s)
    s = s.replace("×", "x").replace("X", "x")
    # 印刷体“÷ 分数”：÷ 1/4、÷ x/(x²-1) 按除以整个分数理解
    s = _wrap_div_fraction(s)
    s = s.replace("÷", "/").replace("·", "*")
    # OCR 丢上标：x2-5x+6 → x^2-5x+6（只在没有 x1/x2 下标写法时，且字母前不是字母）
    if not re.search(r"[a-z][12]\s*[+\-*/,，、和与]\s*[a-z][12]|[a-z]1\b", s):
        s = re.sub(r"(?<![a-zA-Z])([a-z])([23])(?![0-9.])", r"\1^\2", s)
    return s


def _operand_end(s: str, i: int) -> int:
    """从 i 开始读一个操作数（数字 / 单字母 / 括号组，可带 ^n），返回结束位置；读不到返回 -1。"""
    n = len(s)
    while i < n and s[i] == " ":
        i += 1
    if i >= n:
        return -1
    if s[i] == "(":
        depth = 0
        j = i
        while j < n:
            if s[j] == "(":
                depth += 1
            elif s[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= n:
            return -1
        j += 1
    else:
        m = re.match(r"\d+(?:\.\d+)?[a-z]?|[a-z]", s[i:])
        if not m:
            return -1
        j = i + m.end()
    m2 = re.match(r"\^\(?-?\d+\)?", s[j:])
    if m2:
        j += m2.end()
    return j


def _wrap_div_fraction(s: str) -> str:
    out = s
    pos = 0
    while True:
        k = out.find("÷", pos)
        if k < 0:
            return out
        a_end = _operand_end(out, k + 1)
        if a_end > 0:
            rest = out[a_end:]
            ms = re.match(r"\s*/\s*", rest)
            if ms:
                b_end = _operand_end(out, a_end + ms.end())
                if b_end > 0:
                    out = out[: k + 1] + "(" + out[k + 1 : b_end].strip() + ")" + out[b_end:]
        pos = k + 1


_SEG = re.compile(r"(?:sqrt|cbrt|abs|pi|sin|cos|tan|[0-9a-z+\-*/^().=<>≤≥≠\s,;])+")


def _balance_parens(seg: str) -> str:
    """去掉片段两端多余的括号（题面里的“（结果用小数表示）”会留下孤立的左括号）。"""
    for _ in range(4):
        seg = seg.strip(" .,:;")
        if seg.count("(") > seg.count(")") and seg.endswith("("):
            seg = seg[:-1]
            continue
        if seg.count(")") > seg.count("(") and seg.startswith(")"):
            seg = seg[1:]
            continue
        if seg.count("(") > seg.count(")") and seg.startswith("("):
            seg = seg[1:]
            continue
        if seg.count(")") > seg.count("(") and seg.endswith(")"):
            seg = seg[:-1]
            continue
        break
    return seg


def segments(s: str, *, need_digit: bool = True) -> list[str]:
    """抠出数学式子片段（按长度降序）；至少含一个运算符或比较号。"""
    out: list[str] = []
    for m in _SEG.finditer(s):
        seg = _balance_parens(m.group(0))
        if need_digit and not re.search(r"\d", seg):
            continue
        if not re.search(r"[+\-*/^=<>≤≥]|sqrt|abs", seg):
            continue
        out.append(seg)
    out.sort(key=len, reverse=True)
    return out


_FUNCS = {"sqrt": "§", "cbrt": "¢", "abs": "¤", "sin": "ś", "cos": "ć", "tan": "ţ"}
_FUNC_BACK = {"§": "sqrt", "¢": "cbrt", "¤": "abs", "ś": "sin", "ć": "cos", "ţ": "tan"}
_FCHARS = "".join(_FUNC_BACK)


def to_python(expr: str) -> str:
    """学生写法 → Python/SymPy 语法：补隐式乘号、^→**、整数/小数 → 精确有理数。"""
    e = expr.replace(" ", "")
    for k, v in _FUNCS.items():
        e = e.replace(k, v)
    e = e.replace("pi", "π")
    e = re.sub(rf"(\d|π)([a-zπ({_FCHARS}])", r"\1*\2", e)
    e = re.sub(rf"\)([0-9a-zπ({_FCHARS}])", r")*\1", e)
    e = re.sub(rf"([a-zπ])(?=[a-zπ({_FCHARS}0-9])", r"\1*", e)
    e = re.sub(r"(?<=[0-9.])π", "*π", e)
    e = e.replace("^", "**")

    def _num(m: re.Match[str]) -> str:
        t = m.group(0)
        if "." in t:
            whole, frac = t.split(".", 1)
            return f"Rational({int(whole + frac)},{10 ** len(frac)})"
        return f"Integer({int(t)})"

    e = re.sub(r"\d+\.\d+|\d+", _num, e)
    e = e.replace("π", "pi")
    for k, v in _FUNC_BACK.items():
        e = e.replace(k, v)
    e = e.replace("cbrt(", "Rational(1,1)*root3(")
    return e


_ALLOWED = re.compile(r"[0-9a-z+\-*/^().\s]*")


def letters_of(expr: str) -> list[str]:
    e = expr
    for w in ("sqrt", "cbrt", "abs", "pi", "sin", "cos", "tan"):
        e = e.replace(w, "")
    return sorted(set(re.findall(r"[a-z]", e)))


def parse(expr: str, var_names: Iterable[str] = ()) -> Any:
    """解析一个表达式（不含 = / 不等号）；失败抛 ValueError。"""
    if not expr or not expr.strip():
        raise ValueError("empty")
    if not _ALLOWED.fullmatch(expr):
        raise ValueError("unsupported characters")
    if len(expr) > 300:
        raise ValueError("too long")
    rest = expr
    for w in ("sqrt", "cbrt", "abs", "pi", "sin", "cos", "tan"):
        rest = rest.replace(w, " ")
    if re.search(r"[a-z]{3,}", rest):
        raise ValueError("unknown identifier")
    if re.search(r"[a-z]\d", rest):
        raise ValueError("subscripted variable")
    if re.search(r"\^\s*\(?\s*-?\s*(\d{3,}|[2-9]\d)", expr):
        raise ValueError("exponent too large")
    py = to_python(expr)
    if "root3(" in py:
        py = re.sub(r"root3\(([^()]*)\)", r"(\1)**Rational(1,3)", py)
    names = {v: v for v in var_names}
    for v in letters_of(expr):
        names.setdefault(v, v)
    res = runtime().evaluate(py, names, timeout=2.0, simplify_result=False)
    if not res.success:
        raise ValueError(res.error or "parse failed")
    return _realify(res.value)


def _realify(val: Any) -> Any:
    """把自由符号换成实数符号（中学题默认实数范围），便于 Abs/sqrt 化简。"""
    import sympy as sp

    try:
        syms: set = getattr(val, "free_symbols", set())
        if syms:
            return val.xreplace({s: sp.Symbol(s.name, real=True) for s in syms})
    except Exception:  # noqa: BLE001
        return val
    return val


def sym(name: str) -> Any:
    import sympy as sp

    return sp.Symbol(name, real=True)


def fmt(expr: Any) -> str:
    """SymPy → 学生写法：x^2、√3、2x、分数 a/b。"""
    import sympy as sp

    if isinstance(expr, sp.Rational) and not isinstance(expr, sp.Integer):
        return f"{expr.p}/{expr.q}"
    s = sp.sstr(expr, order="lex") if getattr(expr, "free_symbols", None) else sp.sstr(expr)
    s = s.replace("**", "^")
    s = re.sub(r"sqrt\(([0-9a-z]+)\)", r"√\1", s)
    s = s.replace("sqrt(", "√(")
    s = re.sub(r"(\d)\*([a-z√(])", r"\1\2", s)
    s = re.sub(r"(?<![a-z])([a-z])\*([a-z√(])", r"\1\2", s)
    s = re.sub(r"(?<![a-z])([a-z])\*([a-z√(])", r"\1\2", s)
    s = s.replace(")*(", ")(")
    s = s.replace("Abs(", "|").replace("pi", "π")
    if "|" in s:
        s = _close_abs(s)
    return s


def _close_abs(s: str) -> str:
    out, depth_stack = [], []
    depth = 0
    for ch in s:
        if ch == "|":
            depth_stack.append(depth)
            out.append("|")
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth_stack and depth_stack[-1] == depth:
                depth_stack.pop()
                out.append("|")
                continue
            depth -= 1
        out.append(ch)
    return "".join(out)


def value_str(expr: Any) -> str:
    """机器可比对的 sympy 语法字符串。"""
    import sympy as sp

    return sp.sstr(expr).replace(" ", "")


def is_clean_number(v: Any, max_den: int = 100) -> bool:
    import sympy as sp

    if isinstance(v, sp.Integer):
        return True
    if isinstance(v, sp.Rational):
        return abs(int(v.q)) <= max_den
    return False


def numeric_eq(a: Any, b: Any, tol: float = 1e-9) -> bool:
    try:
        return abs(complex(a) - complex(b)) <= tol * max(1.0, abs(complex(b)))
    except (TypeError, ValueError):
        return False


def split_relation(seg: str) -> Optional[tuple[str, str, str]]:
    """'2x-3>5' → ('2x-3', '>', '5')；只认一个关系符。"""
    m = re.findall(r"≤|≥|≠|<|>|=", seg)
    if len(m) != 1:
        return None
    op = m[0]
    lhs, rhs = seg.split(op, 1)
    return lhs.strip(), op, rhs.strip()


__all__ = [
    "fmt",
    "is_clean_number",
    "letters_of",
    "math_normalize",
    "numeric_eq",
    "parse",
    "runtime",
    "segments",
    "split_relation",
    "sym",
    "to_python",
    "value_str",
]
