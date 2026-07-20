"""math_grade — 数学题的确定性符号判分（sympy）。

架构 A：sympy 判分放 mneme app 侧（mneme-core 是零依赖纯库、不含 sympy）。
路由（服务层 SubmitAnswer 用）：数学 solve/fill → 本模块；choice/short/非数学fill →
mneme-core `answer_match`（决策 D2.1）。本模块对**符号等价**判定（"1/2"=="0.5"、
"x=2或x=3"=="x=3,x=2"），sympy 解析失败则回落到归一化精确比对——因此非数学填空
误入本模块也能安全兜底（返回字符串相等判定）。
"""

from __future__ import annotations

import re
import unicodedata

from obase.sympy_runtime import SymPyRuntime

_runtime = SymPyRuntime()

# 多根/多解分隔：逗号（含中文顿号）、分号、"或"、"and"
_SPLIT = re.compile(r"[,，;；、]|\bor\b|\band\b|或")
# 变量赋值前缀，如 "x=" / "x =" / "x1="
_ASSIGN = re.compile(r"^[a-zA-Z]\w*\s*=\s*")

# 题库 expected 大量带 $ 与 LaTeX（\frac \pi \sqrt \leq …），不转 sympy 解析必失败。
_FRAC = re.compile(r"\\?[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_SQRT = re.compile(r"\\sqrt\s*\{([^{}]*)\}")
_LATEX_SPACE = re.compile(r"\\[,;:!>\s]")
_GREEK = re.compile(r"\\(pi|alpha|beta|gamma|theta|lambda|mu|omega)\b")
_STRIP_EDGE = ".,;:!?，。；、'\" \t"


_MATHWRAP = re.compile(r"\\(?:mathrm|mathbf|mathit|text|operatorname)\s*\{([^{}]*)\}")
_SUP = re.compile(r"\^\s*\{([^{}]*)\}")


def _delatex(text: str) -> str:
    """常见 LaTeX 记法 → sympy 可解析/可比对形式。去 $、\\left\\right、转 \\frac/\\sqrt 等。"""
    text = text.replace("$", "")
    text = text.replace("\\left", "").replace("\\right", "")
    text = re.sub(r"\\q?quad", " ", text)
    text = _MATHWRAP.sub(r"\1", text)  # \mathrm{p}→p 等
    text = _SUP.sub(r"^(\1)", text)  # e^{6}→e^(6)（下游 ^→**）
    text = _LATEX_SPACE.sub(" ", text)
    for _ in range(3):  # 允许有限嵌套 frac
        new = _FRAC.sub(r"((\1)/(\2))", text)
        if new == text:
            break
        text = new
    text = _SQRT.sub(r"sqrt(\1)", text)
    text = re.sub(r"\\times|\\cdot", "*", text)
    text = re.sub(r"\\le(?:q|qslant)?\b", "<=", text)
    text = re.sub(r"\\ge(?:q|qslant)?\b", ">=", text)
    text = _GREEK.sub(r"\1", text)
    text = re.sub(r"\\infty\b", "oo", text)  # LaTeX 无穷
    text = text.replace("∞", "oo")  # 学生常直接打 unicode 无穷符号，两边归一同一 token
    return text.replace("\\", "")  # 残余反斜杠去掉（\sin→sin 等），宁可当普通符号


# 隐式乘法（"2x"/"2 pi" -> "2*x"/"2*pi"）：数字与紧随其后的字母之间插入 *，
# 中间可以有空白（"2 pi"）也可以没有（"2x"）——绝不会误伤函数调用（sin/cos/
# sqrt 等函数名前面不会紧跟数字）。S0-W5 改走沙箱化的 obase.sympy_runtime
# （纯 Python ast.parse，不支持 sympy 自己 parse_expr() 的
# implicit_multiplication_application 变换，那个变换在 token 流层面同时处理
# 无空白和有空白两种形式）后，需要在归一化阶段自己补上这条——最初只处理了
# 无空白形式，"2 pi"（LaTeX \pi 去反斜杠后常见的带空格形式）被漏了，
# 全量回归测试 test_pi_and_sqrt 抓到。
_IMPLICIT_MULT_RE = re.compile(r"(?<=[0-9])\s*(?=[A-Za-z])")


def _norm_ops(text: str) -> str:
    """把常见书写归一为 sympy 可解析：LaTeX、× ÷ · ^ 上标、千分位、全半角、首尾标点、
    数字紧跟字母处补隐式乘号（2x -> 2*x）。"""
    text = unicodedata.normalize("NFKC", text)
    text = _delatex(text).strip().strip(_STRIP_EDGE)
    text = text.replace("×", "*").replace("·", "*").replace("÷", "/")
    text = text.replace("^", "**")
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 去千分位逗号 1,000→1000
    return _IMPLICIT_MULT_RE.sub("*", text)


def _normalise_plain(text: str) -> str:
    """回落用的纯文本归一（NFKC/去 LaTeX/小写/空白/首尾标点）。"""
    text = unicodedata.normalize("NFKC", text)
    text = _delatex(text).strip().lower()
    text = re.sub(r"\s+", "", text)  # 数学作答空白不表义，全去（回落比对更稳）
    return text.strip(_STRIP_EDGE)


def _split_top_level(text: str) -> list[str]:
    """按 _SPLIT 切多解，但跳过 `([{`…`)]}` 内部的分隔符（如集合/区间自带的逗号）。"""
    parts = []
    depth = 0
    last = 0
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif depth == 0:
            m = _SPLIT.match(text, i)
            if m:
                parts.append(text[last:i])
                i = m.end()
                last = i
                continue
        i += 1
    parts.append(text[last:])
    return parts


def _to_exprs(raw: str):
    """把一段作答解析成一组 sympy 表达式（多根→集合）。任一失败→None。

    S0-W5：raw 是学生提交的真实作答文本——本模块是 SubmitAnswer 判分主
    链路，全仓真实调用量最大的外部输入入口之一。之前直接用
    sympy.parsing.sympy_parser.parse_expr()，零 AST 白名单/timeout/内存
    上限，同 S0 修过的 solve_* 内核一类风险（AST 全仓扫描才抓到这个点，
    此前 5 个已知发现都是字符串 grep 找到的，这个是纯字符串匹配漏掉、靠
    AST 扫描才揪出来的第 6 个）。改走沙箱化的
    obase.sympy_runtime.evaluate_auto()。
    """
    import sympy as sp

    parts = [p for p in _split_top_level(_norm_ops(raw)) if p.strip()]
    if not parts:
        return None
    exprs = []
    for p in parts:
        p = _ASSIGN.sub("", p.strip())  # 去 "x=" 前缀
        try:
            result = _runtime.evaluate_auto(p, simplify_result=False)
            if not result.success or result.value is None:
                return None
            val = result.value
            if isinstance(
                val, list
            ):  # 方括号区间/列表如 [-1,1] 解出裸 list，非 sympy 对象
                val = sp.Tuple(*val)
            exprs.append(sp.simplify(val))
        except Exception:
            return None
    return exprs


def _expr_eq(x, e) -> bool:  # type: ignore[no-untyped-def]
    """单项等价：先试结构相等（集合/元组等非算术类型 `-` 不报错但也永不为 0，需要 `==`），
    再试代数相减化简（多项式/根式等需要）。"""
    try:
        if bool(x == e):
            return True
    except Exception:
        pass
    import sympy as sp

    try:
        return bool(sp.simplify(x - e) == 0)
    except Exception:
        return False


def grade_math(answer: str, expected: str) -> bool:
    """符号等价判分；sympy 无法解析/无法比对（如不等式、集合）则回落归一化精确比对。"""
    try:
        a_exprs = _to_exprs(answer)
        e_exprs = _to_exprs(expected)
        if a_exprs is not None and e_exprs is not None:
            if len(a_exprs) != len(e_exprs):
                return False
            # 多解按集合比对（顺序无关）：每个期望根都能在作答里找到等价项
            remaining = list(a_exprs)
            for e in e_exprs:
                hit = next(
                    (x for x in remaining if _expr_eq(x, e)),
                    None,
                )
                if hit is None:
                    return False
                remaining.remove(hit)
            return True
    except Exception:
        pass  # 关系式/集合等无法符号相减 → 落字符串回落

    # 回落：非数学/解析失败 → 归一化精确（已去 LaTeX/$/首尾标点）
    return _normalise_plain(answer) == _normalise_plain(expected)
