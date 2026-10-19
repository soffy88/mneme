"""错题变式 + 内核判分。

make_variant(text, seed)：对能被精确内核解出的题，确定性地扰动题面里的数字（随机数种子固定），
用同一个内核重新求解，只接受“同一内核 + 已验证 + 答案干净（不比原题答案更复杂）+ 与原答案不同”的变式。

grade_answer(student, answer_value, answer_kind)：用内核的机器答案判分（数值容差、多值无序、
表达式恒等 + 因式分解形式、不等式解集、文字同义）。
"""

from __future__ import annotations

import random
import re
from fractions import Fraction
from typing import Any, Optional

from services.ask_kernels.core import KernelSolution, basic_normalize
from services.ask_kernels.router import solve_text

_SPECIAL_ANGLES = {"30", "45", "60", "90", "120", "135", "150", "180", "360"}


def _protected(s: str, m: re.Match[str]) -> bool:
    a, b = m.start(), m.end()
    before = s[max(0, a - 3):a]
    after = s[b:b + 3]
    tok = m.group(0)
    if re.search(r"[\^]\s*\(?-?$", before):  # 指数
        return True
    if re.search(r"[A-Z)]$", before) or re.search(r"[a-z]$", before) and not re.search(r"[a-z]\s*$", before[-1:] + " "):
        return True
    if re.search(r"[A-Za-z]$", before):  # x1、H2O、CO2、R1、m/s 中的下标
        return True
    if after.startswith("°") and tok in _SPECIAL_ANGLES:
        return True
    if re.match(r"\s*(?:年|月|日|号|题|班|边形|次方)", after):
        return True
    if re.search(r"第\s*$", before):
        return True
    if tok == "10" and re.match(r"\s*\^", after):  # 科学记数法的底 10
        return True
    if a == 0 and re.match(r"\s*[.、]", after):  # 题号
        return True
    if re.match(r"\s*[:：]\s*\d", after) or re.search(r"\d\s*[:：]\s*$", before):
        return False
    return False


def _perturb_number(tok: str, rng: random.Random, *, coef: bool = False) -> str:
    if "." in tok:
        whole, frac = tok.split(".")
        d = len(frac)
        v = int(whole + frac)
        step = max(1, v // 10)
        nv = v + rng.choice([-1, 1]) * rng.randint(1, max(1, step))
        if nv <= 0:
            nv = v + step
        s = str(nv).rjust(d + 1, "0")
        return s[:-d] + "." + s[-d:]
    v = int(tok)
    if v == 0:
        return tok
    if v <= 10:
        lo = 2 if (coef or v >= 2) else 1
        choices = [x for x in range(max(lo, v - 3), v + 4) if x != v]
    elif v % 10 == 0:
        mag = 10 ** (len(tok) - 1) if v % (10 ** (len(tok) - 1)) == 0 else 10
        choices = [v + k * mag for k in (-3, -2, -1, 1, 2, 3) if v + k * mag > 0]
    else:
        span = max(2, v // 5)
        choices = [x for x in range(max(1, v - span), v + span + 1) if x != v]
    return str(rng.choice(choices))


def _clean_enough(new: KernelSolution, orig: KernelSolution) -> bool:
    nv, ov = new.answer_value, orig.answer_value
    if not nv or nv == ov:
        return False
    if "sqrt" in nv and "sqrt" not in ov:
        return False
    if "pi" in nv and "pi" not in ov:
        return False
    if len(nv) > len(ov) + 6:
        return False
    dens = [int(d) for d in re.findall(r"/(\d+)", nv)]
    odens = [int(d) for d in re.findall(r"/(\d+)", ov)]
    if dens and max(dens) > max(odens + [12]):
        return False
    if "." in nv and "." not in ov and "/" not in ov:
        decs = re.findall(r"\.(\d+)", nv)
        if any(len(d) > 2 for d in decs):
            return False
    onums = re.findall(r"-?\d+(?:\.\d+)?(?:/\d+)?", ov)
    nnums = re.findall(r"-?\d+(?:\.\d+)?(?:/\d+)?", nv)
    if onums and all(re.fullmatch(r"-?\d+", x) for x in onums) and "sqrt" not in ov:
        if not all(re.fullmatch(r"-?\d+", x) for x in nnums):
            return False
    if onums and nnums and new.kernel.startswith(("word", "physics", "chemistry", "ratio")):
        try:
            r = abs(float(Fraction(nnums[0]))) / max(1e-9, abs(float(Fraction(onums[0]))))
        except (ValueError, ZeroDivisionError):
            return False
        if not 0.5 <= r <= 2:
            return False
    if "-" in nv and "-" not in ov and new.answer_kind in ("num",) and new.kernel.startswith(("word", "geometry", "physics", "chemistry", "stats", "prob", "unit", "ratio")):
        return False
    return True


def make_variant(text: str, seed: int, *, original: Optional[KernelSolution] = None, subject: Optional[str] = None,
                 attempts: int = 40, budget_s: Optional[float] = None) -> Optional[dict[str, Any]]:
    """同类变式题（确定性）。返回 {text, solution(dict), kernel}；做不出干净的变式返回 None。

    ``budget_s`` 默认关闭：同一 (text, seed) 必须得到同一结果，不能因为机器负载
    /覆盖率插桩导致“同一调用有时超时返回 None”。需要线上时延上限的调用方
    （如错题复习）显式传 budget_s。
    """
    base = text if not re.search(r"[０-９]", text) else basic_normalize(text)
    orig = original or solve_text(base, subject)
    if orig is None:
        return None
    toks = [m for m in re.finditer(r"\d+(?:\.\d+)?", base) if not _protected(base, m)]
    if not toks:
        return None
    rng = random.Random(seed)
    import time

    t0 = time.monotonic()
    for _ in range(attempts):
        if budget_s is not None and time.monotonic() - t0 > budget_s:
            break
        # 每次改 1~全部 个数字
        k = rng.randint(1, len(toks))
        pick = set(rng.sample(range(len(toks)), k))
        out, last = [], 0
        for i, m in enumerate(toks):
            out.append(base[last:m.start()])
            nxt = base[m.end():m.end() + 1]
            prv = base[max(0, m.start() - 1):m.start()]
            coef = bool(re.match(r"[a-z(（√]", nxt) or prv == "/")
            out.append(_perturb_number(m.group(0), rng, coef=coef) if i in pick else m.group(0))
            last = m.end()
        out.append(base[last:])
        vt = "".join(out)
        if vt == base:
            continue
        # A single candidate must not be silently dropped because of a transient
        # CPU spike; the outer budget (when supplied) still bounds the call.
        sol = solve_text(
            vt, subject, budget_s=budget_s if budget_s is not None else 30.0
        )
        if sol is None or sol.kernel != orig.kernel or not sol.verified or sol.answer_kind != orig.answer_kind:
            continue
        if not _clean_enough(sol, orig):
            continue
        return {"text": vt, "kernel": sol.kernel, "solution": sol.to_dict()}
    return None


# ── 内核判分 ─────────────────────────────────────────────────────────────────


def _to_expr(s: str) -> Any:
    from services.ask_kernels.sym import letters_of, math_normalize, parse

    t = math_normalize(s).strip()
    t = re.sub(r"^[a-z]\s*=\s*", "", t) if t.count("=") == 1 else t
    return parse(t, "".join(letters_of(t)))


def _num_tokens(s: str) -> list[Any]:
    """答案里的数值（支持 3/4、-2、√3、2√3、π、0.5、50%）。"""
    import sympy as sp

    t = basic_normalize(s)
    t = re.sub(r"[a-zA-Z]\s*[₁₂12]?\s*=", " ", t)
    t = t.replace("π", "pi")
    pat = re.compile(r"-?\s*(?:\d+(?:\.\d+)?)?\s*(?:√\s*\d+|√\(\d+\)|sqrt\(\d+\))(?:\s*/\s*\d+)?|-?\(?\d+(?:\.\d+)?\s*[+\-]\s*√\d+\)?\s*/\s*\d+|-?\d+(?:\.\d+)?(?:\s*/\s*\d+(?:\.\d+)?)?\s*(?:pi|%)?|-?pi")
    out = []
    for m in pat.finditer(t):
        tok = m.group(0).replace(" ", "")
        if not tok or tok == "-":
            continue
        try:
            if tok.endswith("%"):
                out.append(sp.Rational(tok[:-1]) / 100)
                continue
            out.append(_to_expr(tok))
        except (ValueError, TypeError):
            continue
    return out


def _parse_answer_values(value: str) -> list[Any]:
    from services.ask_kernels.sym import parse

    vals = []
    for part in value.split(","):
        p = part.strip()
        if not p:
            continue
        p = re.sub(r"^[a-z]\s*=\s*", "", p)
        try:
            vals.append(parse(p.replace("**", "^")))
        except ValueError:
            return []
    return vals


def _close(a: Any, b: Any) -> bool:
    try:
        fa, fb = complex(a), complex(b)
    except (TypeError, ValueError):
        return False
    return abs(fa - fb) <= max(1e-9, 1e-3 * max(1.0, abs(fb)))


_INEQ = re.compile(r"^(?:(-?[\d./]+)(<=|<)([a-z])(<=|<)(-?[\d./]+)|([a-z])(<=|>=|<|>)(-?[\d./]+))$")


def _ineq_tuple(s: str) -> Optional[tuple]:
    t = basic_normalize(s).replace(" ", "").replace("≤", "<=").replace("≥", ">=")
    if re.search(r"无解|空集", t):
        return ("empty",)
    m = _INEQ.match(t)
    if not m:
        return None
    if m.group(1):
        return (Fraction(m.group(1)), m.group(2) == "<=", Fraction(m.group(5)), m.group(4) == "<=")
    op, v = m.group(7), Fraction(m.group(8))
    if op in ("<", "<="):
        return (None, False, v, op == "<=")
    return (v, op == ">=", None, False)


_TEXT_SYN = [
    ("无实数根", r"无实数根|没有实数根|无实根|没有实根"),
    ("无解", r"无解|没有解|无实数解"),
    ("两个不相等的实数根", r"两个不相等|两个不等"),
    ("两个相等的实数根", r"两个相等"),
]


def grade_answer(student: str, answer_value: str, answer_kind: str, unit: str = "") -> Optional[bool]:
    """True/False；判不了（格式无法解析）返回 None。"""
    import sympy as sp

    a = (student or "").strip()
    if unit == "%":
        a = a.replace("%", "").replace("％", "")
    if not a:
        return False
    if answer_kind == "text":
        for canon, pat in _TEXT_SYN:
            if canon == answer_value or re.search(pat, answer_value):
                return bool(re.search(pat, a))
        return basic_normalize(a).replace(" ", "") == basic_normalize(answer_value).replace(" ", "")
    if answer_kind == "ineq":
        st, ex = _ineq_tuple(a), _ineq_tuple(answer_value)
        if ex is None:
            return None
        if st is None:
            return None
        return st == ex
    if answer_kind == "expr":
        try:
            se, ee = _to_expr(a), _to_expr(answer_value.replace("**", "^"))
        except ValueError:
            return None
        if sp.simplify(sp.expand(se - ee)) != 0:
            return False
        # 因式分解题：学生必须写成乘积形式
        if isinstance(ee, (sp.Mul, sp.Pow)) and not isinstance(se, (sp.Mul, sp.Pow)):
            return False
        return True
    expected = _parse_answer_values(answer_value)
    if not expected:
        return None
    got = _num_tokens(a)
    if not got:
        return None
    if answer_kind == "num" or len(expected) == 1:
        return any(_close(g, expected[0]) for g in got[-1:]) or (len(got) == 1 and _close(got[0], expected[0]))
    if len(got) != len(expected):
        return False
    rest = list(expected)
    for g in got:
        hit = next((i for i, e in enumerate(rest) if _close(g, e)), None)
        if hit is None:
            return False
        rest.pop(hit)
    return True


__all__ = ["grade_answer", "make_variant"]
