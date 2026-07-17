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

# 多根/多解分隔：逗号、分号、"或"、"and"
_SPLIT = re.compile(r"[,，;；]|\bor\b|\band\b|或")
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
    return text.replace("\\", "")  # 残余反斜杠去掉（\sin→sin 等），宁可当普通符号


def _norm_ops(text: str) -> str:
    """把常见书写归一为 sympy 可解析：LaTeX、× ÷ · ^ 上标、千分位、全半角、首尾标点。"""
    text = unicodedata.normalize("NFKC", text)
    text = _delatex(text).strip().strip(_STRIP_EDGE)
    text = text.replace("×", "*").replace("·", "*").replace("÷", "/")
    text = text.replace("^", "**")
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 去千分位逗号 1,000→1000
    return text


def _normalise_plain(text: str) -> str:
    """回落用的纯文本归一（NFKC/去 LaTeX/小写/空白/首尾标点）。"""
    text = unicodedata.normalize("NFKC", text)
    text = _delatex(text).strip().lower()
    text = re.sub(r"\s+", "", text)  # 数学作答空白不表义，全去（回落比对更稳）
    return text.strip(_STRIP_EDGE)


def _to_exprs(raw: str):
    """把一段作答解析成一组 sympy 表达式（多根→集合）。任一失败→None。"""
    import sympy as sp
    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    transforms = standard_transformations + (implicit_multiplication_application,)
    parts = [p for p in _SPLIT.split(_norm_ops(raw)) if p.strip()]
    if not parts:
        return None
    exprs = []
    for p in parts:
        p = _ASSIGN.sub("", p.strip())  # 去 "x=" 前缀
        try:
            exprs.append(sp.simplify(parse_expr(p, transformations=transforms)))
        except Exception:
            return None
    return exprs


def grade_math(answer: str, expected: str) -> bool:
    """符号等价判分；sympy 无法解析/无法比对（如不等式、集合）则回落归一化精确比对。"""
    try:
        a_exprs = _to_exprs(answer)
        e_exprs = _to_exprs(expected)
        if a_exprs is not None and e_exprs is not None:
            import sympy as sp

            if len(a_exprs) != len(e_exprs):
                return False
            # 多解按集合比对（顺序无关）：每个期望根都能在作答里找到等价项
            remaining = list(a_exprs)
            for e in e_exprs:
                hit = next(
                    (x for x in remaining if sp.simplify(x - e) == 0),
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
