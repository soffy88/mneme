"""拍照问题目精确内核的公共部件：结果类型、题面规范化、数字格式化。

不依赖 sympy（物理/化学/应用题/统计内核只用 fractions.Fraction 精确计算），
sympy 相关的解析统一在 ``services.ask_kernels.sym`` 里走沙箱。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Optional, Union

Num = Union[int, Fraction]


@dataclass
class KernelSolution:
    """一个内核给出的已验证解答。

    - ``answer``：给学生看的最终答案（中文、带单位）；
    - ``answer_value``：机器可比对的答案（判分/变式用），约定：
        num   → "3/4"、"2*sqrt(3)"、"8*pi"、"12.5"
        nums  → "x=1, y=2" 或 "1, 2"（按题目所问顺序）
        expr  → sympy 语法表达式 "(x-2)*(x+3)"
        ineq  → "x>2"、"-1<x<=3"、"无解"
        text  → 简短中文（如 "无实数根"）
    - ``check``：验证方式（代入检验/逆运算/守恒复核），verified=False 的解不会返回给学生；
    - ``confidence``：解析置信度（0-1），路由只接受 ≥ 0.6。
    """

    kernel: str
    answer: str
    steps: list[str] = field(default_factory=list)
    hint: str = ""
    explanation: str = ""
    answer_value: str = ""
    answer_kind: str = "num"
    unit: str = ""
    verified: bool = True
    check: str = ""
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kernel": self.kernel,
            "answer": self.answer,
            "steps": self.steps,
            "hint": self.hint,
            "explanation": self.explanation,
            "answer_value": self.answer_value or self.answer,
            "answer_kind": self.answer_kind,
            "unit": self.unit,
            "verified": self.verified,
            "check": self.check,
            "confidence": round(float(self.confidence), 3),
        }


# ── 规范化 ──────────────────────────────────────────────────────────────────

_FW = {chr(c): chr(c - 0xFEE0) for c in range(0xFF01, 0xFF5F)}
_FW["\u3000"] = " "
_PUNCT = {
    "，": ",", "。": ". ", "；": ";", "：": ":", "（": "(", "）": ")", "【": "[", "】": "]",
    "〔": "(", "〕": ")", "｛": "{", "｝": "}", "＜": "<", "＞": ">", "？": "?", "！": "!",
    "−": "-", "–": "-", "—": "-", "－": "-", "‐": "-", "﹣": "-", "＝": "=", "﹦": "=",
    "×": "×", "✕": "×", "╳": "×", "÷": "÷", "∶": ":", "·": "·", "•": "·", "⋅": "·",
    "≦": "≤", "≧": "≥", "⩽": "≤", "⩾": "≥", "π": "π", "Π": "π",
    "’": "'", "‘": "'", "“": '"', "”": '"', "℃": "℃", "°C": "℃",
}
_SUP = str.maketrans({"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7",
                      "⁸": "8", "⁹": "9", "⁻": "-"})
_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_VULGAR = {"½": "(1/2)", "⅓": "(1/3)", "⅔": "(2/3)", "¼": "(1/4)", "¾": "(3/4)", "⅕": "(1/5)",
           "⅖": "(2/5)", "⅗": "(3/5)", "⅘": "(4/5)", "⅙": "(1/6)", "⅚": "(5/6)", "⅛": "(1/8)",
           "⅜": "(3/8)", "⅝": "(5/8)", "⅞": "(7/8)"}


def basic_normalize(text: str) -> str:
    """全角→半角、中文标点、上下标、OCR 常见混淆（O/0、l/1）。保留中文与单位符号。"""
    s = text or ""
    s = "".join(_FW.get(ch, ch) for ch in s)
    for a, b in _PUNCT.items():
        s = s.replace(a, b)
    for a, b in _VULGAR.items():
        s = s.replace(a, b)
    # 上标：x² → x^2，10⁻³ → 10^(-3)
    s = re.sub(r"([⁻]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)", lambda m: "^" + _wrap_neg(m.group(1).translate(_SUP)), s)
    s = s.translate(_SUB)
    # OCR：数字之间的 O/o → 0，l/I/| 在数字之间 → 1
    # （数字串前面是字母的，如 H2O、CO2、x2，属于化学式/下标，不动）
    s = re.sub(r"(?<![A-Za-z\d.])(\d+(?:\.\d*)?)[Oo](?=\d|\.\d)", lambda m: m.group(1) + "0", s)
    s = re.sub(r"(?<![A-Za-z\d.])(\d+)[Oo](?=\s*(?:kg|g|m|cm|km|N|Pa|J|W|V|A|s|%|元|米|克|千克|个|人|天)(?![a-z]))", lambda m: m.group(1) + "0", s)
    s = re.sub(r"(?<![A-Za-z\d.])(\d+)[lI](?=\d)", lambda m: m.group(1) + "1", s)
    s = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", s)  # "3 . 5" → 3.5
    s = s.replace("<=", "≤").replace(">=", "≥").replace("!=", "≠")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _wrap_neg(e: str) -> str:
    return f"({e})" if e.startswith("-") else e


# ── 数字 ────────────────────────────────────────────────────────────────────

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def cn_small_number(s: str) -> Optional[int]:
    """一~九十九 的中文数字 → int（应用题里常见“三小时”“两人”）。"""
    s = s.strip()
    if not s:
        return None
    if s in _CN_DIGITS:
        return _CN_DIGITS[s]
    m = re.fullmatch(r"([一二三四五六七八九])?十([一二三四五六七八九])?", s)
    if m:
        tens = _CN_DIGITS[m.group(1)] if m.group(1) else 1
        ones = _CN_DIGITS[m.group(2)] if m.group(2) else 0
        return tens * 10 + ones
    return None


def to_frac(s: str) -> Fraction:
    """"12"、"-3.5"、"3/4"、"2又1/3"、"40%" → Fraction（精确）。"""
    t = s.strip().replace(" ", "")
    neg = t.startswith("-")
    if neg:
        t = t[1:]
    pct = t.endswith("%")
    if pct:
        t = t[:-1]
    m = re.fullmatch(r"(\d+)又(\d+)/(\d+)", t)
    if m:
        v = Fraction(int(m.group(1))) + Fraction(int(m.group(2)), int(m.group(3)))
    elif "/" in t:
        a, b = t.split("/", 1)
        v = Fraction(Fraction(a), Fraction(b))
    else:
        v = Fraction(t)
    if pct:
        v /= 100
    return -v if neg else v


def fmt_num(v: Num, *, max_dec: int = 6, prefer_decimal: bool = False) -> str:
    """Fraction → 学生习惯的写法：整数、有限小数（≤ max_dec 位）或最简分数。"""
    f = Fraction(v)
    if f.denominator == 1:
        return str(f.numerator)
    if prefer_decimal or _is_terminating(f):
        d = _terminating_digits(f)
        if d is not None and d <= max_dec:
            return _dec_str(f, d)
    return f"{f.numerator}/{f.denominator}"


def fmt_frac(v: Num) -> str:
    f = Fraction(v)
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


def fmt_approx(v: Num, sig: int = 4) -> str:
    x = float(v)
    if x == 0:
        return "0"
    digits = max(0, sig - 1 - int(math.floor(math.log10(abs(x)))))
    s = f"{x:.{min(digits, 10)}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _is_terminating(f: Fraction) -> bool:
    d = f.denominator
    for p in (2, 5):
        while d % p == 0:
            d //= p
    return d == 1


def _terminating_digits(f: Fraction) -> Optional[int]:
    if not _is_terminating(f):
        return None
    d = f.denominator
    n = 0
    while d != 1:
        n += 1
        if d % 10 == 0:
            d //= 10
        elif d % 2 == 0:
            d //= 2
        elif d % 5 == 0:
            d //= 5
        f2 = f * 10**n
        if f2.denominator == 1:
            return n
    return n


def _dec_str(f: Fraction, digits: int) -> str:
    neg = f < 0
    a = abs(f) * 10**digits
    q = a.numerator // a.denominator
    s = str(q).rjust(digits + 1, "0")
    out = s[:-digits] + "." + s[-digits:] if digits else s
    out = out.rstrip("0").rstrip(".") if "." in out else out
    return ("-" if neg else "") + out


def fmt_sig(v: Num) -> str:
    """物理量结果：精确能写成 ≤4 位小数就写精确值，否则保留 3 位有效数字附近。"""
    f = Fraction(v)
    d = _terminating_digits(f)
    if f.denominator == 1 or (d is not None and d <= 4):
        return fmt_num(f, max_dec=4)
    return fmt_approx(f, 4)


NUM_RE = re.compile(r"(?<![A-Za-z_])-?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?")


def numbers_in(text: str) -> list[Fraction]:
    out = []
    for m in re.finditer(r"\d+(?:\.\d+)?", text):
        out.append(Fraction(m.group(0)))
    return out


def strip_question_number(text: str) -> str:
    """去掉行首题号（"3." "（2）" "例1" "第5题"），避免把题号当已知量。"""
    t = text.strip()
    t = re.sub(r"^\s*(?:例\s*\d+|第\s*\d+\s*题|\d{1,2}\s*[.、．](?!\d)|[(（]\s*\d{1,2}\s*[)）]|[①②③④⑤⑥⑦⑧⑨⑩])\s*", "", t)
    return t


# ── LaTeX 题面（题库/教辅文本常见）→ 印刷体 ─────────────────────────────────

_LATEX_HINT = re.compile(r"\$|\\(?:frac|dfrac|left|right|sqrt|cdot|times|div|qquad|quad|pi|circ|angle|triangle|le|ge|neq)\b|\^\{|_\{")
_LATEX_SYMS = {
    r"\cdot": "·", r"\times": "×", r"\div": "÷", r"\pi": "π", r"\angle": "∠", r"\triangle": "△",
    r"\leqslant": "≤", r"\geqslant": "≥", r"\leq": "≤", r"\geq": "≥", r"\le": "≤", r"\ge": "≥", r"\neq": "≠",
    r"\pm": "±", r"\because": "因为", r"\therefore": "所以", r"\%": "%", r"\{": "{", r"\}": "}",
    r"\sin": "sin", r"\cos": "cos", r"\tan": "tan", r"\cot": "cot", r"\log": "log", r"\lg": "lg", r"\ln": "ln",
    r"\ldots": "…", r"\cdots": "…", r"\dots": "…", r"\alpha": "α", r"\beta": "β", r"\theta": "θ", r"\rho": "ρ",
    r"\backsim": "∽", r"\sim": "∽", r"\cong": "≌", r"\perp": "⊥", r"\parallel": "∥", r"\infty": "∞",
}
_BRACE = r"\{((?:[^{}]|\{[^{}]*\})*)\}"


def latex_to_plain(text: str) -> str:
    """把题库里的 LaTeX 写法转成内核认识的印刷体：$…$、\\frac{a}{b}→(a)/(b)、x^{2}→x^2、
    x_{1}→x1、\\sqrt{3}→√(3)、^{\\circ}→°、\\qquad/\\underline{…}→（ ）。不含 LaTeX 的文本原样返回。"""
    s = text or ""
    if not _LATEX_HINT.search(s):
        return s
    s = s.replace("\\$", "$")
    s = re.sub(r"(?<![a-zA-Z\\])(frac|qquad|sqrt)(?=[{\s])", r"\\\1", s)  # 丢了反斜杠的 frac{1}{5}
    s = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg)(?![a-zA-Z])\s*([(){}\[\].|]|\\\{|\\\}|\\\||)", lambda m: "" if m.group(1) in (".", "") else m.group(1), s)
    s = re.sub(r"\\(?:displaystyle|textstyle|mathrm|text|operatorname|boldsymbol|mathbf)\s*", "", s)
    s = re.sub(r"\^\s*\{\s*\\circ\s*\}|\^\s*\\circ|\\circ", "°", s)
    s = re.sub(r"\\(?:qquad|quad)\b|\\underline\s*\{\s*(?:\\[a-z]+\s*)*\}|\\_+|_{2,}", "（ ）", s)
    for _ in range(4):
        s2 = re.sub(r"\\[dt]?frac\s*" + _BRACE + r"\s*" + _BRACE, r"(\1)/(\2)", s)
        s2 = re.sub(r"\\[dt]?frac\s*(\d)\s*(\d)", r"(\1)/(\2)", s2)
        s2 = re.sub(r"\\sqrt\s*\[\s*3\s*\]\s*" + _BRACE, r"³√(\1)", s2)
        s2 = re.sub(r"\\sqrt\s*" + _BRACE, r"√(\1)", s2)
        s2 = re.sub(r"\\sqrt\s*(\d+|[a-z])", r"√\1", s2)
        s2 = re.sub(r"\^\s*\{\s*(-?\d+|[a-z])\s*\}", r"^\1", s2)
        s2 = re.sub(r"\^\s*" + _BRACE, r"^(\1)", s2)
        s2 = re.sub(r"_\s*\{\s*([0-9a-zA-Z]+)\s*\}", r"\1", s2)
        if s2 == s:
            break
        s = s2
    s = re.sub(r"\\begin\s*\{(?:array|cases|aligned)\}\s*(?:\{[^{}]*\})?|\\end\s*\{(?:array|cases|aligned)\}", "", s)
    s = s.replace("\\\\", "; ")
    for a, b in sorted(_LATEX_SYMS.items(), key=lambda kv: -len(kv[0])):
        s = re.sub(re.escape(a) + (r"(?![a-zA-Z])" if a[-1].isalpha() else ""), b, s)
    s = s.replace("$", " ")
    s = re.sub(r"\\[a-zA-Z]+", " ", s)
    s = re.sub(r"\(\s*\)|（\s*）", "（ ）", s)
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


__all__ = [
    "KernelSolution",
    "NUM_RE",
    "Num",
    "basic_normalize",
    "cn_small_number",
    "fmt_approx",
    "fmt_frac",
    "latex_to_plain",
    "fmt_num",
    "fmt_sig",
    "numbers_in",
    "strip_question_number",
    "to_frac",
]
