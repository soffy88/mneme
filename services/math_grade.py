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


def _norm_ops(text: str) -> str:
    """把常见书写归一为 sympy 可解析：× ÷ · ^ 上标、千分位、全半角。"""
    text = unicodedata.normalize("NFKC", text)
    text = text.strip()
    text = text.replace("×", "*").replace("·", "*").replace("÷", "/")
    text = text.replace("^", "**")
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 去千分位逗号 1,000→1000
    return text


def _normalise_plain(text: str) -> str:
    """回落用的纯文本归一（同 answer_match 语义：NFKC/小写/空白/首尾标点）。"""
    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip(".,;:!?\"'")


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
    """符号等价判分；sympy 无法解析则回落归一化精确比对。"""
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

    # 回落：非数学/解析失败 → 归一化精确
    return _normalise_plain(answer) == _normalise_plain(expected)
