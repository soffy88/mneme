"""朗读文本规整（服务层纯函数，无 IO）：LaTeX/数学符号 → 口语中文、TTS 友好化、分句。

- ``latex_to_speech("(a+b)^2")`` → ``"a加b的平方"``
- ``tts_ready(text)``：latex_to_speech + 去 Markdown + 拉丁字母读音（中文 TTS 词典不含英文字母）
- ``split_sentences(text)``：按句末标点切句，供流式逐句 TTS（首句先出声）。

确定性、可单测；不调用 LLM。
"""

from __future__ import annotations

import re

_GREEK = {
    "alpha": "阿尔法", "beta": "贝塔", "gamma": "伽马", "delta": "德尔塔", "theta": "西塔",
    "lambda": "兰姆达", "mu": "缪", "sigma": "西格玛", "omega": "欧米伽", "phi": "斐",
    "varphi": "斐", "rho": "柔", "epsilon": "艾普西龙", "varepsilon": "艾普西龙",
    "Delta": "德尔塔", "Omega": "欧米伽", "Sigma": "西格玛",
}
_FUNCS = {
    "sin": "正弦", "cos": "余弦", "tan": "正切", "cot": "余切", "log": "对数",
    "ln": "自然对数", "lg": "常用对数", "max": "最大值", "min": "最小值", "lim": "极限",
}
_SYMBOLS = [
    (r"\\times", "乘"), (r"\\cdot", "乘"), (r"\\div", "除以"), (r"\\pm", "正负"), (r"\\mp", "负正"),
    (r"\\neq", "不等于"), (r"\\ne\b", "不等于"), (r"\\leq?\b", "小于等于"), (r"\\geq?\b", "大于等于"),
    (r"\\leqslant", "小于等于"), (r"\\geqslant", "大于等于"), (r"\\approx", "约等于"),
    (r"\\equiv", "恒等于"), (r"\\sim", "相似于"), (r"\\cong", "全等于"),
    (r"\\because", "因为"), (r"\\therefore", "所以"), (r"\\infty", "无穷大"),
    (r"\\pi", "派"), (r"\\angle", "角"), (r"\\triangle", "三角形"), (r"\\perp", "垂直于"),
    (r"\\parallel", "平行于"), (r"\\in\b", "属于"), (r"\\notin", "不属于"),
    (r"\\subseteq", "包含于"), (r"\\subset", "真包含于"), (r"\\cup", "并"), (r"\\cap", "交"),
    (r"\\emptyset", "空集"), (r"\\varnothing", "空集"), (r"\\Rightarrow", "推出"),
    (r"\\rightarrow", "趋向于"), (r"\\to\b", "趋向于"), (r"\\Leftrightarrow", "等价于"),
    (r"\\circ", "度"), (r"\\%", "%"), (r"\\degree", "度"),
]
_UNICODE = [
    ("×", "乘"), ("·", "乘"), ("÷", "除以"), ("±", "正负"), ("≠", "不等于"), ("≤", "小于等于"),
    ("≥", "大于等于"), ("≈", "约等于"), ("∠", "角"), ("△", "三角形"), ("⊥", "垂直于"),
    ("∥", "平行于"), ("∞", "无穷大"), ("π", "派"), ("√", "根号"), ("°", "度"),
    ("∵", "因为"), ("∴", "所以"), ("≌", "全等于"), ("∽", "相似于"),
]
_SUPERSCRIPTS = {"²": "^2", "³": "^3", "¹": "^1", "⁴": "^4", "ⁿ": "^n", "⁻¹": "^{-1}"}


def _brace_arg(s: str, i: int) -> tuple[str, int]:
    """从 s[i] 起取一个 TeX 参数：{...}（配平）或单字符；返回 (内容, 结束下标)。"""
    while i < len(s) and s[i] == " ":
        i += 1
    if i >= len(s):
        return "", i
    if s[i] != "{":
        return s[i], i + 1
    depth, j = 0, i
    while j < len(s):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1 : j], j + 1
        j += 1
    return s[i + 1 :], len(s)


def _expand_structures(s: str) -> str:
    """\\frac / \\sqrt / \\text 等带参结构 → 口语（递归处理嵌套）。"""
    out: list[str] = []
    i = 0
    while i < len(s):
        m = re.match(r"\\(d|t)?frac", s[i:])
        if m:
            num, j = _brace_arg(s, i + m.end())
            den, j = _brace_arg(s, j)
            out.append(f"{_expand_structures(den)}分之{_expand_structures(num)}")
            i = j
            continue
        m = re.match(r"\\sqrt", s[i:])
        if m:
            j = i + m.end()
            idx = ""
            if j < len(s) and s[j] == "[":
                k = s.find("]", j)
                if k > 0:
                    idx, j = s[j + 1 : k], k + 1
            body, j = _brace_arg(s, j)
            body_s = _expand_structures(body)
            if idx and idx.strip() not in ("2",):
                out.append(f"{body_s}的{_expand_structures(idx)}次方根")
            else:
                out.append(f"根号{body_s}")
            i = j
            continue
        m = re.match(r"\\(text|mathrm|mathbf|textbf|operatorname|boxed|overline|bar)\b", s[i:])
        if m:
            body, j = _brace_arg(s, i + m.end())
            out.append(_expand_structures(body))
            i = j
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def _strip_parens(base: str) -> str:
    base = base.strip()
    if len(base) >= 2 and base[0] in "(（" and base[-1] in ")）":
        return base[1:-1]
    return base


def _power_word(exp: str) -> str:
    e = exp.strip()
    if e == "2":
        return "的平方"
    if e == "3":
        return "的立方"
    if e in ("-1", "{-1}"):
        return "的负一次方"
    if e.startswith("-"):
        return f"的负{e[1:]}次方"
    return f"的{e}次方"


def _expand_powers(s: str) -> str:
    """X^e → X的e次方；(a+b)^2 → a加b的平方（括号底数去括号）。"""
    while True:
        m = re.search(r"\^", s)
        if not m:
            return s
        k = m.start()
        # 取底数：紧邻的括号组或单个"词"
        j = k - 1
        while j >= 0 and s[j] == " ":
            j -= 1
        if j >= 0 and s[j] in ")）":
            depth, b = 0, j
            while b >= 0:
                if s[b] in ")）":
                    depth += 1
                elif s[b] in "(（":
                    depth -= 1
                    if depth == 0:
                        break
                b -= 1
            start = max(b, 0)
        else:
            start = j
            while start > 0 and re.match(r"[0-9A-Za-z.]", s[start - 1]):
                start -= 1
        base = _strip_parens(s[start : j + 1]) if j >= 0 else ""
        exp, end = _brace_arg(s, k + 1)
        s = s[:start] + base + _power_word(exp) + s[end:]


def latex_to_speech(text: str) -> str:
    """把含 LaTeX / 数学符号的文本转成可朗读中文。未知命令去反斜杠保留名字。"""
    if not text:
        return ""
    s = text
    s = re.sub(r"\$\$|\$|\\\(|\\\)|\\\[|\\\]", " ", s)
    for k, v in _SUPERSCRIPTS.items():
        s = s.replace(k, v)
    s = re.sub(r"\^\s*\{?\s*\\circ\s*\}?", "度", s)
    s = re.sub(r"\\left|\\right|\\displaystyle|\\,|\\;|\\!|\\quad|\\qquad", " ", s)
    s = s.replace("\\{", "{").replace("\\}", "}")
    s = _expand_structures(s)
    for pat, rep in _SYMBOLS:
        s = re.sub(pat, rep, s)
    for name, rep in _GREEK.items():
        s = re.sub(rf"\\{name}\b", rep, s)
    for name, rep in _FUNCS.items():
        s = re.sub(rf"\\{name}\b", rep, s)
    for k, v in _UNICODE:
        s = s.replace(k, v)
    s = _expand_powers(s)
    s = re.sub(r"_\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"_([0-9A-Za-z])", r"\1", s)
    # 百分数 / 简单分数 a/b
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"百分之\1", s)
    s = re.sub(r"(?<![\w.])(\d+)\s*/\s*(\d+)(?![\w.])", r"\2分之\1", s)
    # 关系与运算符（负号：行首/左括号/运算符后 → 负）
    s = re.sub(r"(^|[=(（,，:：<>]\s*)-\s*(?=[\dA-Za-z])", r"\1负", s)
    s = s.replace("<=", "小于等于").replace(">=", "大于等于").replace("!=", "不等于")
    s = re.sub(r"\s*=\s*", "等于", s)
    s = re.sub(r"\s*\+\s*", "加", s)
    s = re.sub(r"(?<=[\w)）])\s*-\s*(?=[\w(（])", "减", s)
    s = re.sub(r"\s*<\s*", "小于", s)
    s = re.sub(r"\s*>\s*", "大于", s)
    s = re.sub(r"(?<=[\w)）])\s*\*\s*(?=[\w(（])", "乘", s)
    s = re.sub(r"\\([A-Za-z]+)", r"\1", s)
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"(?<=[\u4e00-\u9fff]) | (?=[\u4e00-\u9fff])", "", s)
    return s.strip()


# 中文 TTS（matcha zh-baker）词典无英文：孤立拉丁字母按常见中文读法给音
_LETTERS = {
    "a": "诶", "b": "必", "c": "西", "d": "低", "e": "伊", "f": "艾弗", "g": "鸡", "h": "艾尺",
    "i": "艾", "j": "杰", "k": "开", "l": "艾勒", "m": "艾姆", "n": "恩", "o": "欧", "p": "批",
    "q": "扣", "r": "阿", "s": "艾斯", "t": "提", "u": "优", "v": "维", "w": "达不溜",
    "x": "艾克斯", "y": "歪", "z": "贼",
}


def _strip_markdown(s: str) -> str:
    s = re.sub(r"```.*?```", " ", s, flags=re.S)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[*_#>`|~]+", " ", s)
    return s


def tts_ready(text: str, *, spell_letters: bool = True) -> str:
    """送入中文 TTS 前的最终文本：去 Markdown → LaTeX 口语化 → 拉丁字母读音。"""
    s = latex_to_speech(_strip_markdown(text or ""))
    if spell_letters:
        s = re.sub(
            r"(?<![A-Za-z])([A-Za-z]{1,3})(?![A-Za-z])",
            lambda m: "".join(_LETTERS.get(c.lower(), c) for c in m.group(1)),
            s,
        )
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"(?<=[\u4e00-\u9fff]) (?=[\w])|(?<=[\w]) (?=[\u4e00-\u9fff])", "", s)
    return s


_SENT_END = re.compile(r"(?<=[。！？!?；;\n])")


def split_sentences(text: str, *, max_len: int = 60) -> list[str]:
    """按句末标点分句；过长句再按逗号切，保证首句尽快合成出声。"""
    out: list[str] = []
    for part in _SENT_END.split(text or ""):
        p = part.strip()
        if not p:
            continue
        while len(p) > max_len:
            cut = max(p.rfind("，", 0, max_len), p.rfind(",", 0, max_len))
            if cut <= 0:
                cut = max_len
            out.append(p[: cut + 1].strip())
            p = p[cut + 1 :].strip()
        if p:
            out.append(p)
    return out
