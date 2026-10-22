"""AetherViz 课内小测验答案键的确定性核验（Layer 4 服务层，纯函数，不碰 DB）。

LLM 生成的单选题答案键可能是错的（cnm_148 Q2：两个选项都成立，键只认一个）。这里用 sympy
对能机械判定的题型核验「恰好键定的那一项正确」：

- ``identity``：题干无公式（或只提到单个字母），每个选项都是一条等式 ``L = R``——判
  ``expand(L - R) == 0``（如「下列计算正确的是」）。
- ``value``：题干恰有一个目标式（可带 ``x=2`` 之类代入），选项都是不含等号的式子/数——判
  选项与目标式恒等（如「计算 (x+3)^2 的结果」「(a-b)^2=」）。
- 题干含「错误/不正确/不成立…」时取反：正确项 = 不成立的项。

解析器是本模块自带的小型 TeX 递归下降解析，直接用 sympy 构造器建表达式——**不**调用
sympify/parse_expr/eval（S0-W5 全仓 AST 审计红线），指数/整数位数有上限防 DoS。解析不了、
题型不在上面两类（解方程、求参数、因式分解、±、不等式…）一律 ``unverifiable``——调用方
据此不回写 BKT，而不是猜。
"""

from __future__ import annotations

import re
from typing import Any

import sympy as sp

MAX_EXP = 12
MAX_DIGITS = 12
MAX_LEN = 240

_MATH_SEG = re.compile(r"\$\$(.+?)\$\$|\\\((.+?)\\\)|\\\[(.+?)\\\]|\$(.+?)\$", re.S)
_NEGATED = re.compile(r"错误|不正确|不成立|不相等|不等于|不是|有误|不对")
_UNSUPPORTED_PROMPT = re.compile(r"因式分解|分解因式|解方程|方程的解|的解是|取值范围|最大值|最小值|完全平方式|求\s*[a-zA-Z]\s*的值")
_RESERVED_LETTERS = {"e", "i"}  # 自然常数/虚数单位语义不明，宁可判不了


class Unparsable(Exception):
    """表达式超出本解析器支持范围。"""


# --------------------------------------------------------------------------- TeX → sympy


def _normalize(tex: str) -> str:
    s = tex.strip()
    for a, b in (
        ("−", "-"),
        ("–", "-"),
        ("×", "*"),
        ("·", "*"),
        ("÷", "/"),
        ("²", "^2"),
        ("³", "^3"),
        ("（", "("),
        ("）", ")"),
        ("＝", "="),
        ("＋", "+"),
    ):
        s = s.replace(a, b)
    s = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg)(?![a-zA-Z])", "", s)
    s = re.sub(r"\\(?:cdot|times)(?![a-zA-Z])", "*", s)
    s = re.sub(r"\\div(?![a-zA-Z])", "/", s)
    s = re.sub(r"\\[dt]frac(?![a-zA-Z])", r"\\frac", s)
    s = re.sub(r"\\(?:,|;|!|:|quad|qquad)|~", " ", s)
    return s


_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|(\\[a-zA-Z]+)|([a-zA-Z])|([-+*/^(){}\[\]=]))")


def _tokenize(s: str) -> list[str]:
    out: list[str] = []
    pos = 0
    s = s.rstrip()
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m or m.end() == pos:
            raise Unparsable(f"bad char at {pos}: {s[pos:pos + 8]!r}")
        tok = next(g for g in m.groups() if g is not None)
        if tok.startswith("\\") and tok not in ("\\frac", "\\sqrt", "\\pi"):
            raise Unparsable(f"unsupported command {tok}")
        if len(tok) > 1 and tok[0].isdigit() and len(tok.replace(".", "")) > MAX_DIGITS:
            raise Unparsable("number too long")
        if tok in _RESERVED_LETTERS:
            raise Unparsable(f"reserved letter {tok}")
        out.append(tok)
        pos = m.end()
    return out


class _Parser:
    def __init__(self, toks: list[str]) -> None:
        self.t = toks
        self.i = 0

    def peek(self) -> str | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, want: str | None = None) -> str:
        tok = self.peek()
        if tok is None or (want is not None and tok != want):
            raise Unparsable(f"expected {want!r} got {tok!r}")
        self.i += 1
        return tok

    def done(self) -> bool:
        return self.i >= len(self.t)

    # expr := term (('+'|'-') term)*
    def expr(self) -> sp.Expr:
        node = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            rhs = self.term()
            node = node + rhs if op == "+" else node - rhs
        return node

    def _starts_atom(self, tok: str | None) -> bool:
        return tok is not None and (
            tok[0].isdigit() or tok.isalpha() or tok in ("(", "[", "{", "\\frac", "\\sqrt", "\\pi")
        )

    # term := unary (('*'|'/') unary | implicit-atom)*
    def term(self) -> sp.Expr:
        node = self.unary()
        while True:
            tok = self.peek()
            if tok in ("*", "/"):
                self.take()
                rhs = self.unary()
                if tok == "/":
                    if rhs == 0:
                        raise Unparsable("division by zero")
                    node = node / rhs
                else:
                    node = node * rhs
            elif self._starts_atom(tok):
                if tok is not None and tok[0].isdigit() and self.t[self.i - 1][0].isdigit():
                    raise Unparsable("adjacent numbers")
                node = node * self.power()
            else:
                return node

    def unary(self) -> sp.Expr:
        if self.peek() == "-":
            self.take()
            return -self.unary()
        if self.peek() == "+":
            self.take()
            return self.unary()
        return self.power()

    # power := atom ('^' exponent)?
    def power(self) -> sp.Expr:
        base = self.atom()
        if self.peek() == "^":
            self.take()
            if self.peek() == "-":
                self.take()
                ex = -self.atom()
            else:
                ex = self.atom()
            if ex.free_symbols:
                raise Unparsable("symbolic exponent")
            if not ex.is_Rational or abs(ex) > MAX_EXP:
                raise Unparsable("exponent out of range")
            return sp.Pow(base, ex)
        return base

    def _group(self, open_: str, close: str) -> sp.Expr:
        self.take(open_)
        node = self.expr()
        self.take(close)
        return node

    def atom(self) -> sp.Expr:
        tok = self.peek()
        if tok is None:
            raise Unparsable("unexpected end")
        if tok[0].isdigit():
            self.take()
            return sp.Rational(tok)
        if tok == "\\pi":
            self.take()
            return sp.pi
        if tok.isalpha() and len(tok) == 1:
            self.take()
            return sp.Symbol(tok)
        if tok == "(":
            return self._group("(", ")")
        if tok == "[":
            return self._group("[", "]")
        if tok == "{":
            return self._group("{", "}")
        if tok == "\\frac":
            self.take()
            num = self._brace_or_atom()
            den = self._brace_or_atom()
            if den == 0:
                raise Unparsable("division by zero")
            return num / den
        if tok == "\\sqrt":
            self.take()
            n: sp.Expr = sp.Integer(2)
            if self.peek() == "[":
                n = self._group("[", "]")
                if not (n.is_Integer and 2 <= n <= MAX_EXP):
                    raise Unparsable("bad root index")
            return sp.root(self._brace_or_atom(), n)
        raise Unparsable(f"unexpected {tok!r}")

    def _brace_or_atom(self) -> sp.Expr:
        if self.peek() == "{":
            return self._group("{", "}")
        tok = self.peek()
        if tok is not None and tok[0].isdigit() and len(tok) > 1 and "." not in tok:
            # \frac12 → 1/2：TeX 单字符参数
            self.t[self.i] = tok[1:]
            return sp.Integer(int(tok[0]))
        return self.atom()


def parse_tex(tex: str) -> sp.Expr:
    """单个 TeX 表达式（不含等号）→ sympy 表达式；不支持即抛 Unparsable。"""
    s = _normalize(tex)
    if not s or len(s) > MAX_LEN:
        raise Unparsable("empty or too long")
    p = _Parser(_tokenize(s))
    node = p.expr()
    if not p.done():
        raise Unparsable(f"trailing {p.peek()!r}")
    return node


def _strip_delims(s: str) -> str:
    s = s.strip()
    segs = _MATH_SEG.findall(s)
    if segs:
        rest = _MATH_SEG.sub("", s)
        if rest.strip(" ，,.。;；:：ABCDabcd()（）"):
            raise Unparsable("text outside math")
        if len(segs) != 1:
            raise Unparsable("multiple math segments")
        return next(g for g in segs[0] if g)
    return s


def parse_option(choice: str) -> tuple[sp.Expr, sp.Expr | None]:
    """选项 → (左式, 右式或 None)。"""
    body = _strip_delims(choice)
    body = re.sub(r"^\s*[A-D][.、．]\s*", "", body)
    parts = _normalize(body).split("=")
    if len(parts) == 1:
        return parse_tex(parts[0]), None
    if len(parts) == 2:
        return parse_tex(parts[0]), parse_tex(parts[1])
    raise Unparsable("chained equation")


def _is_zero(d: sp.Expr) -> bool:
    d = sp.expand(d)
    if d == 0:
        return True
    if d.free_symbols:
        z = sp.simplify(d)
        return bool(z == 0)
    v = d.equals(0)
    if v is None:
        raise Unparsable("undecidable")
    return bool(v)


# --------------------------------------------------------------------------- 题目核验


def _prompt_parts(prompt: str) -> tuple[list[str], dict[sp.Symbol, sp.Expr]]:
    segs = [next(g for g in m if g) for m in _MATH_SEG.findall(prompt)]
    subs: dict[sp.Symbol, sp.Expr] = {}
    targets: list[str] = []
    for seg in segs:
        n = _normalize(seg)
        m = re.fullmatch(r"\s*([a-zA-Z])\s*=\s*(.+?)\s*", n)
        if m and not re.search(r"[a-zA-Z]", re.sub(r"\\(?:frac|sqrt)", "", m.group(2))):
            subs[sp.Symbol(m.group(1))] = parse_tex(m.group(2))
            continue
        for chunk in re.split(r"[,，;；]", n):
            chunk = chunk.strip()
            m2 = re.fullmatch(r"([a-zA-Z])\s*=\s*(-?[\d.]+)", chunk)
            if m2:
                subs[sp.Symbol(m2.group(1))] = sp.Rational(m2.group(2))
            elif chunk:
                targets.append(chunk)
    text = _MATH_SEG.sub(" ", prompt)
    for m in re.finditer(r"(?<![a-zA-Z])([a-zA-Z])\s*=\s*(-?\d+(?:\.\d+)?)", text):
        subs[sp.Symbol(m.group(1))] = sp.Rational(m.group(2))
    return targets, subs


def verify_item(item: dict[str, Any]) -> dict[str, Any]:
    """核验单题：status ∈ verified / defect / unverifiable；correct=判定为正确的选项下标。"""
    prompt = str(item.get("prompt") or "")
    choices = [str(c) for c in item.get("choices") or []]
    answer = item.get("answer")
    if _UNSUPPORTED_PROMPT.search(prompt):
        return {"status": "unverifiable", "reason": "unsupported_prompt"}
    try:
        targets, subs = _prompt_parts(prompt)
        opts = [parse_option(c) for c in choices]
    except Unparsable as e:
        return {"status": "unverifiable", "reason": f"parse:{e}"[:120]}
    except Exception as e:  # noqa: BLE001 — sympy 内部异常也当判不了
        return {"status": "unverifiable", "reason": f"error:{type(e).__name__}"}
    negated = bool(_NEGATED.search(_MATH_SEG.sub(" ", prompt)))
    try:
        if all(r is not None for _, r in opts):
            mode = "identity"
            if subs or any(not re.fullmatch(r"\s*[a-zA-Z]\s*", t) for t in targets):
                return {"status": "unverifiable", "reason": "identity_with_conditions"}
            for lhs, rhs in opts:
                assert rhs is not None
                for a, b in ((lhs, rhs), (rhs, lhs)):
                    if isinstance(a, sp.Symbol) and not b.free_symbols:
                        return {"status": "unverifiable", "reason": "solution_claim"}
            truth = [_is_zero(lhs - rhs) for lhs, rhs in opts if rhs is not None]
        elif all(r is None for _, r in opts):
            mode = "value"
            if len(targets) != 1:
                return {"status": "unverifiable", "reason": f"targets:{len(targets)}"}
            t = re.sub(r"=\s*(\?|？|\\underline\{[^}]*\}|_+)?\s*$", "", targets[0])
            if "=" in t:
                return {"status": "unverifiable", "reason": "target_has_equation"}
            target = parse_tex(t).subs(subs)
            truth = [_is_zero(target - lhs.subs(subs)) for lhs, _ in opts]
        else:
            return {"status": "unverifiable", "reason": "mixed_options"}
    except Unparsable as e:
        return {"status": "unverifiable", "reason": f"parse:{e}"[:120]}
    except Exception as e:  # noqa: BLE001
        return {"status": "unverifiable", "reason": f"error:{type(e).__name__}"}
    correct = [i for i, ok in enumerate(truth) if ok != negated]
    status = "verified" if correct == [answer] else "defect"
    return {"status": status, "mode": mode, "negated": negated, "correct": correct}


def verify_quiz(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """逐题核验，返回与 items 等长的结果列表。"""
    return [verify_item(it) for it in items]
