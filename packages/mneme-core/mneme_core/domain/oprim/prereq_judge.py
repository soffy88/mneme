"""mneme-core prereq_judge — 先修诊断题的确定性判题（cn-math-taxonomy 题库）。

忠实移植自上游 cn-math-taxonomy ``diagnose/engine.js`` 的判题部分
（judgeQuestion / judgeAnswer / normalizeText），CC BY-NC 4.0，
https://github.com/xiaoyang111222/cn-math-taxonomy 。

只在"可靠"时给 correct / wrong，其余一律 ``manual``（交学生对照参考答案自评）：
  - choice  比字母（也接受选项文字）
  - numeric 数值等价（整数/小数/分数/带分数/百分数/角度/单位/坐标/多答案）
  - short   规范化精确匹配 + accept 列表
  - self    永远 manual
  - legacy  （来自 diagnostic_question）按参考答案文本判

Pure functions, no IO。与 ``grade.answer_match``（非数学客观题）互不调用；
数学求解类结论仍以 sympy 内核为准——本模块只比对题库自带的参考答案。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

Verdict = dict[str, str]  # {"verdict": correct|wrong|manual, "reason": ...}

_HAN = "一-龥"


def normalize_text(value: Any) -> str:
    """规范化：全角转半角、去空格、中文标点、度、千分位、去"答："前缀。"""
    s = "" if value is None else str(value)
    s = s.replace("²", "^2").replace("³", "^3")
    s = re.sub("[º˚∘゜]", "°", s)
    s = unicodedata.normalize("NFKC", s)
    s = re.sub("[−‐-―﹣]", "-", s)
    s = s.replace("、", ",").replace("。", ".")
    s = re.sub("[“”‘’]", '"', s)
    s = re.sub("[×·⋅∙]", "*", s)
    s = s.replace("÷", "/")
    s = re.sub("[≦⩽]", "≤", s)
    s = re.sub("[≧⩾]", "≥", s)
    s = s.replace("<=", "≤").replace(">=", "≥")
    s = re.sub(r"[\[\]{}]", lambda m: "(" if m.group(0) in "[{" else ")", s)
    s = re.sub(r"([0-9])\s*度", r"\1°", s)
    s = re.sub(r"([0-9])\s+([0-9]+\s*/\s*[0-9]+)", r"\1又\2", s)  # 带分数 "1 1/2"
    s = re.sub(r"\s+", "", s).lower()
    s = re.sub(r"^(答案|答)[:=]", "", s).replace("或者", "或")
    s = re.sub(r"[.!]+\Z", "", s)
    if re.fullmatch(r"[+-]?[0-9]{1,3}(,[0-9]{3})+(\.[0-9]+)?", s):
        s = s.replace(",", "")
    return s


def _split_top(s: str, seps: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    cur = ""
    for c in s:
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        if depth == 0 and c in seps:
            parts.append(cur)
            cur = ""
        else:
            cur += c
    parts.append(cur)
    return [p for p in parts if p != ""]


def _gcd(a: int, b: int) -> int:
    a, b = abs(a), abs(b)
    while b:
        a, b = b, a % b
    return a


def _ratio(n: int, d: int) -> tuple[int, int] | None:
    if d == 0:
        return None
    if d < 0:
        n, d = -n, -d
    g = _gcd(n, d) or 1
    return (n // g, d // g)


def _dec_to_ratio(s: str) -> tuple[int, int] | None:
    i = s.find(".")
    if i < 0:
        return _ratio(int(s), 1)
    frac = s[i + 1 :]
    whole = s[:i] or "0"
    return _ratio(int(whole + frac), 10 ** len(frac))


def _is_wrapped(t: str) -> bool:
    if not t or t[0] != "(" or t[-1] != ")":
        return False
    depth = 0
    for i, c in enumerate(t):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0 and i < len(t) - 1:
                return False
    return depth == 0


_UNIT_ALIASES = {
    "米": "m", "m": "m", "厘米": "cm", "cm": "cm", "毫米": "mm", "mm": "mm", "千米": "km",
    "公里": "km", "km": "km", "千克": "kg", "公斤": "kg", "kg": "kg", "克": "g", "g": "g",
    "秒": "s", "s": "s", "分钟": "min", "min": "min", "小时": "h", "h": "h",
    "平方米": "m^2", "m^2": "m^2", "平方厘米": "cm^2", "cm^2": "cm^2",
    "立方米": "m^3", "m^3": "m^3", "立方厘米": "cm^3", "cm^3": "cm^3",
    "元": "元", "度": "°", "°": "°",
}


def _canon_unit(u: str) -> dict[str, Any] | None:
    if not u:
        return {"name": "", "known": True}
    if u in _UNIT_ALIASES:
        return {"name": _UNIT_ALIASES[u], "known": True}
    if re.fullmatch(f"[{_HAN}]{{1,4}}", u):
        return {"name": u, "known": False}
    return None  # 不像单位，说明这不是"数+单位"


_NUM_RE = re.compile(
    r"([+-]?)(?:([0-9]+)又)?([0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
    r"(?:/([0-9]+(?:\.[0-9]+)?|\.[0-9]+))?(%|°)?(.*)",
    re.DOTALL,
)


def _parse_numeric(s: str) -> dict[str, Any] | None:
    """整数、小数、分数、带分数、百分数、带符号/括号；末尾可带单位。失败返回 None。"""
    t = s
    neg = False
    for _ in range(4):
        if _is_wrapped(t):
            t = t[1:-1]
            continue
        if t and t[0] in "+-" and _is_wrapped(t[1:]):
            if t[0] == "-":
                neg = not neg
            t = t[2:-1]
            continue
        break
    m = _NUM_RE.fullmatch(t)
    if not m:
        return None
    sign, whole, num_s, den_s, mark, rest = m.groups()
    rest = rest or ""
    if whole and not den_s:
        return None
    val: tuple[int, int] | None
    if whole:
        n0, d0 = _dec_to_ratio(num_s), _dec_to_ratio(den_s)
        if not n0 or not d0 or d0[0] == 0:
            return None
        f = _ratio(n0[0] * d0[1], n0[1] * d0[0])
        w = _ratio(int(whole), 1)
        assert f is not None and w is not None
        val = _ratio(w[0] * f[1] + f[0], f[1])
    elif den_s:
        n0, d0 = _dec_to_ratio(num_s), _dec_to_ratio(den_s)
        if not n0 or not d0 or d0[0] == 0:
            return None
        val = _ratio(n0[0] * d0[1], n0[1] * d0[0])
    else:
        val = _dec_to_ratio(num_s)
    if not val:
        return None
    if sign == "-":
        neg = not neg
    n = -val[0] if neg else val[0]
    d = val[1]
    unit: dict[str, Any] | None = {"name": "", "known": True}
    if mark == "%":
        r = _ratio(n, d * 100)
        assert r is not None
        n, d = r
        if rest:
            return None
    elif mark == "°":
        unit = {"name": "°", "known": True}
        if not re.fullmatch(f"[{_HAN}]{{0,2}}", rest):
            return None
    elif rest:
        unit = _canon_unit(rest)
        if not unit:
            return None
    return {"key": f"{n}/{d}", "unit": unit}


def _analyze_part(p: str) -> dict[str, Any]:
    variable = ""
    body = p
    m = re.fullmatch(r"([a-z](?:\([a-z]\))?)=(.+)", p, re.DOTALL)
    if m:
        variable, body = m.group(1), m.group(2)
    num = _parse_numeric(body)
    if num:
        return {"raw": p, "variable": variable, "kind": "num", "key": num["key"], "unit": num["unit"]}
    tm = re.fullmatch(r"\((.+)\)", body, re.DOTALL)
    if tm:
        items = _split_top(tm.group(1), ",")
        nums = [_parse_numeric(x) for x in items]
        if len(items) > 1 and all(nums):
            key = "t:" + ",".join(x["key"] for x in nums if x)
            return {"raw": p, "variable": variable, "kind": "tuple", "key": key,
                    "unit": {"name": "", "known": True}}
    return {"raw": p, "variable": variable, "kind": "text", "key": body,
            "unit": {"name": "", "known": True}}


def _parse_answer(value: Any) -> dict[str, Any]:
    norm = normalize_text(value)
    parts = [_analyze_part(p) for p in _split_top(re.sub("[和或与及]", ",", norm), ",;")]
    return {"norm": norm, "parts": parts}


def _part_compare(a: dict[str, Any], b: dict[str, Any]) -> str:
    if a["kind"] != b["kind"] or a["key"] != b["key"]:
        return "ne"
    ua, ub = a["unit"], b["unit"]
    if not ua["name"] or not ub["name"] or ua["name"] == ub["name"]:
        return "eq"
    return "ne" if ua["known"] and ub["known"] else "unsure"


def _same_multiset(as_: list[dict[str, Any]], bs: list[dict[str, Any]], ignore_var: bool) -> str | None:
    if len(as_) != len(bs):
        return None
    left = list(bs)
    fuzzy = False
    for a in as_:
        hit = -1
        for j, b in enumerate(left):
            if not ignore_var and a["variable"] != b["variable"]:
                continue
            c = _part_compare(a, b)
            if c == "ne":
                continue
            if c == "unsure":
                fuzzy = True
            hit = j
            break
        if hit < 0:
            return None
        left.pop(hit)
    return "unsure" if fuzzy else "eq"


def _all_numeric(parts: list[dict[str, Any]]) -> bool:
    return all(p["kind"] in ("num", "tuple") for p in parts)


def _compare_parsed(u: dict[str, Any], r: dict[str, Any]) -> str:
    res: str | None = None
    up, rp = u["parts"], r["parts"]
    if len(up) == len(rp):
        ref_vars = [p["variable"] for p in rp]
        distinct = len(rp) > 1 and all(ref_vars) and len(set(ref_vars)) == len(ref_vars)
        if distinct:
            if all(p["variable"] for p in up):
                res = _same_multiset(up, rp, False)
            elif all(not p["variable"] for p in up):
                # 未写变量名时按参考答案的出现顺序对应（x 在前 y 在后）
                res = "eq"
                for a, b in zip(up, rp):
                    c = _part_compare(a, b)
                    if c == "ne":
                        res = None
                        break
                    if c == "unsure":
                        res = "unsure"
            else:
                return "unsure"
        else:
            res = _same_multiset(up, rp, True)
    if res == "eq":
        return "equal"
    if res == "unsure":
        return "unsure"
    return "different" if _all_numeric(up) and _all_numeric(rp) else "unsure"


def judge_answer(user: Any, reference: Any) -> Verdict:
    """只按参考答案文本判（legacy 接口）。"""
    u = _parse_answer(user)
    r = _parse_answer(reference)
    if not u["norm"]:
        return {"verdict": "manual", "reason": "empty"}
    if u["norm"] == r["norm"]:
        return {"verdict": "correct", "reason": "identical"}
    if not r["parts"]:
        return {"verdict": "manual", "reason": "no-reference"}
    rel = _compare_parsed(u, r)
    if rel == "equal":
        return {"verdict": "correct", "reason": "equivalent"}
    if rel == "different":
        return {"verdict": "wrong", "reason": "numeric-mismatch"}
    return {"verdict": "manual", "reason": "unsure"}


def _manual_empty() -> Verdict:
    return {"verdict": "manual", "reason": "empty"}


def _judge_choice(user: Any, q: dict[str, Any]) -> Verdict:
    raw = ("" if user is None else str(user)).strip()
    if not raw:
        return _manual_empty()
    choices = q.get("choices") or []
    keys = [c.get("key") for c in choices]
    letter: str | None = None
    m = re.fullmatch(r"[(（]?([A-Za-z])[)）.．、:：]?", raw)
    if m:
        letter = m.group(1).upper()
    else:
        n = normalize_text(raw)
        hit = next((c for c in choices if normalize_text(c.get("text")) == n), None)
        if hit:
            letter = hit.get("key")
    if not letter or letter not in keys:
        return {"verdict": "manual", "reason": "unrecognized"}
    return {"verdict": "correct" if letter == q.get("answer") else "wrong", "reason": "choice"}


def _judge_numeric(user: Any, q: dict[str, Any]) -> Verdict:
    u = _parse_answer(user)
    if not u["norm"]:
        return _manual_empty()
    refs = [q.get("answer")] + list(q.get("accept") or [])
    for ref in refs:
        if _parse_answer(ref)["norm"] == u["norm"]:
            return {"verdict": "correct", "reason": "identical"}
    main = _parse_answer(q.get("answer"))
    if not q.get("unordered") and len(main["parts"]) > 1:
        # 多个答案且顺序有关：逐项按顺序比较（变量名忽略）
        if len(u["parts"]) != len(main["parts"]):
            if _all_numeric(u["parts"]):
                return {"verdict": "wrong", "reason": "count-mismatch"}
            return {"verdict": "manual", "reason": "unsure"}
        res = "eq"
        for a, b in zip(u["parts"], main["parts"]):
            c = _part_compare(a, b)
            if c == "ne":
                res = "ne"
                break
            if c == "unsure":
                res = "unsure"
        if res == "eq":
            return {"verdict": "correct", "reason": "equivalent"}
        if res == "ne" and _all_numeric(u["parts"]) and _all_numeric(main["parts"]):
            return {"verdict": "wrong", "reason": "numeric-mismatch"}
        return {"verdict": "manual", "reason": "unsure"}
    r = judge_answer(user, q.get("answer"))
    if r["verdict"] == "correct":
        return r
    for ref in refs[1:]:
        if judge_answer(user, ref)["verdict"] == "correct":
            return {"verdict": "correct", "reason": "accept"}
    return r


def _judge_short(user: Any, q: dict[str, Any]) -> Verdict:
    u = normalize_text(user)
    if not u:
        return _manual_empty()
    refs = [q.get("answer")] + list(q.get("accept") or [])
    for i, ref in enumerate(refs):
        if normalize_text(ref) == u:
            return {"verdict": "correct", "reason": "accept" if i else "identical"}
    for ref in refs:
        if judge_answer(user, ref)["verdict"] == "correct":
            return {"verdict": "correct", "reason": "equivalent"}
    return {"verdict": "manual", "reason": "unsure"}  # 文字/代数式写法太多，交自评


def judge_question(q: dict[str, Any], user: Any) -> Verdict:
    """按题型判题，返回 {"verdict": "correct"|"wrong"|"manual", "reason": str}。"""
    qtype = q.get("type")
    if qtype == "choice":
        return _judge_choice(user, q)
    if qtype == "numeric":
        return _judge_numeric(user, q)
    if qtype == "short":
        return _judge_short(user, q)
    if qtype == "self":
        return {"verdict": "manual", "reason": "self"}
    return judge_answer(user, q.get("answer"))  # legacy：来自 diagnostic_question
