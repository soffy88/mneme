"""函数内核：一次函数（两点式、斜率截距、求值、与坐标轴交点）、二次函数（顶点/对称轴/与 x 轴交点/最值/三点式）、反比例函数。"""

from __future__ import annotations

import re
from typing import Any, Optional

from services.ask_kernels.core import KernelSolution, basic_normalize
from services.ask_kernels.sym import fmt, letters_of, math_normalize, parse, sym, value_str

_PT = re.compile(r"([A-Z]?)\s*\(\s*(-?\d+(?:\.\d+)?(?:/\d+)?)\s*,\s*(-?\d+(?:\.\d+)?(?:/\d+)?)\s*\)")


def _points(raw: str) -> list[tuple[str, Any, Any]]:
    import sympy as sp

    out = []
    for m in _PT.finditer(raw):
        out.append((m.group(1), sp.Rational(m.group(2)), sp.Rational(m.group(3))))
    return out


def _func_expr(s: str) -> Optional[tuple[str, Any]]:
    """题面里的 y = f(x)。返回 (原式字符串, sympy 表达式)。"""
    m = re.search(r"y\s*=\s*([0-9a-z+\-*/^().\s]+?)(?=[,;:.]|[^\x00-\x7f]|$)", s)
    if not m:
        return None
    e = m.group(1).strip()
    if not e or set(letters_of(e)) - {"x", "k", "b", "a", "c", "m"}:
        return None
    try:
        return e, parse(e, "x")
    except ValueError:
        return None


def _ask_order(raw: str, keys: dict[str, str]) -> list[str]:
    found = []
    for k, pat in keys.items():
        m = re.search(pat, raw)
        if m:
            found.append((m.start(), k))
    return [k for _, k in sorted(found)]


def solve_linear_function(text: str) -> Optional[KernelSolution]:
    import sympy as sp

    raw = basic_normalize(text)
    if not re.search(r"一次函数|正比例函数|直线|y\s*=\s*k\s*x", raw):
        return None
    if re.search(r"二次函数|反比例|抛物线", raw):
        return None
    s = math_normalize(text)
    x = sym("x")
    pts = _points(raw)
    steps: list[str] = []
    fe = _func_expr(s)
    expr: Any = None
    if fe and not ({"k", "b"} & set(letters_of(fe[0]))) and not (len(pts) >= 2 and re.search(r"经过|过点", raw)):
        expr = fe[1]
        if sp.Poly(expr, x).degree() != 1:
            return None
        steps.append(f"一次函数 y = {fmt(expr)}")
    else:
        prop = bool(re.search(r"正比例", raw))
        if prop and len(pts) >= 1:
            _, x0, y0 = pts[0]
            if x0 == 0:
                return None
            kv = y0 / x0
            expr = kv * x
            steps.append(f"设 y = kx，把 ({fmt(x0)}, {fmt(y0)}) 代入：{fmt(y0)} = {fmt(x0)}k，k = {fmt(kv)}")
        elif len(pts) >= 2:
            (_, x1, y1), (_, x2, y2) = pts[0], pts[1]
            if x1 == x2:
                return None
            kv = (y2 - y1) / (x2 - x1)
            bv = y1 - kv * x1
            expr = kv * x + bv
            steps.append(f"设 y = kx + b，把 ({fmt(x1)}, {fmt(y1)})、({fmt(x2)}, {fmt(y2)}) 代入得方程组：")
            steps.append(f"{fmt(x1)}k + b = {fmt(y1)}；{fmt(x2)}k + b = {fmt(y2)}")
            steps.append(f"两式相减：k = ({fmt(y2)} - {fmt(y1)}) / ({fmt(x2)} - {fmt(x1)}) = {fmt(kv)}，b = {fmt(bv)}")
            for _, xi, yi in pts[:2]:
                if expr.subs(x, xi) != yi:
                    return None
        else:
            return None
        if kv == 0:
            return None
        steps.append(f"所以函数解析式为 y = {fmt(expr)}")
    kv = sp.Poly(expr, x).all_coeffs()[0]
    bv = expr.subs(x, 0)
    asks = _ask_order(raw, {
        "eval": r"(?:当|求)\s*x\s*=\s*-?\d",
        "xval": r"(?:当|求)\s*y\s*=\s*-?\d",
        "xint": r"与\s*x\s*轴.{0,4}交点",
        "yint": r"与\s*y\s*轴.{0,4}交点(?!.{0,4}截距)",
        "k": r"(?<![a-z])k\s*(?:的值|=\s*\?|(?:与|和|、)\s*b\s*的值)|斜率",
        "b": r"(?<![a-z])b\s*的值|截距",
        "area": r"(?:与|和)两?坐标轴.{0,8}三角形.{0,4}面积",
    })
    vals: list[str] = []
    ans_parts: list[str] = []
    for a in asks:
        if a == "eval":
            m = re.search(r"(?:当|求)\s*x\s*=\s*(-?\d+(?:\.\d+)?(?:/\d+)?)", raw)
            assert m
            xv = sp.Rational(m.group(1))
            yv = expr.subs(x, xv)
            steps.append(f"当 x = {fmt(xv)} 时，y = {fmt(expr.subs(x, sp.Symbol('□')))}".replace("□", f"({fmt(xv)})") + f" = {fmt(yv)}")
            vals.append(value_str(yv))
            ans_parts.append(f"y = {fmt(yv)}")
        elif a == "xval":
            m = re.search(r"(?:当|求)\s*y\s*=\s*(-?\d+(?:\.\d+)?(?:/\d+)?)", raw)
            assert m
            yv = sp.Rational(m.group(1))
            xv = (yv - bv) / kv
            steps.append(f"令 {fmt(expr)} = {fmt(yv)}，解得 x = {fmt(xv)}")
            vals.append(value_str(xv))
            ans_parts.append(f"x = {fmt(xv)}")
        elif a == "xint":
            xv = -bv / kv
            steps.append(f"与 x 轴交点：令 y = 0，{fmt(expr)} = 0，x = {fmt(xv)}，交点 ({fmt(xv)}, 0)")
            vals += [value_str(xv), "0"]
            ans_parts.append(f"与 x 轴交于 ({fmt(xv)}, 0)")
        elif a == "yint":
            steps.append(f"与 y 轴交点：令 x = 0，y = {fmt(bv)}，交点 (0, {fmt(bv)})")
            vals += ["0", value_str(bv)]
            ans_parts.append(f"与 y 轴交于 (0, {fmt(bv)})")
        elif a == "k":
            vals.append(value_str(kv))
            ans_parts.append(f"k = {fmt(kv)}")
            if re.search(r"k\s*(?:与|和|、)\s*b\s*的值", raw) and "b" not in asks:
                vals.append(value_str(bv))
                ans_parts.append(f"b = {fmt(bv)}")
        elif a == "b":
            vals.append(value_str(bv))
            ans_parts.append(f"b = {fmt(bv)}")
        elif a == "area":
            xv = -bv / kv
            area = abs(xv) * abs(bv) / 2
            steps.append(f"与两坐标轴交于 ({fmt(xv)}, 0) 和 (0, {fmt(bv)})，面积 = ½×{fmt(abs(xv))}×{fmt(abs(bv))} = {fmt(area)}")
            vals.append(value_str(area))
            ans_parts.append(f"面积 = {fmt(area)}")
    if not asks:
        if fe and not pts:
            return None  # 只给了解析式却没问什么
        ans_parts = [f"y = {fmt(expr)}"]
        vals = [value_str(expr)]
        kind = "expr"
    else:
        kind = "nums" if len(vals) > 1 else "num"
    return KernelSolution(
        kernel="function.linear",
        answer="；".join(ans_parts),
        steps=steps,
        hint="待定系数法：设 y = kx + b，把已知点的坐标代入，解关于 k、b 的方程组；求交点就令另一个坐标为 0。",
        explanation="一次函数：待定系数法、与坐标轴的交点。",
        answer_value=", ".join(vals),
        answer_kind=kind,
        check="已知点代入解析式成立",
    )


def solve_quadratic_function(text: str) -> Optional[KernelSolution]:
    import sympy as sp

    raw = basic_normalize(text)
    if not re.search(r"二次函数|抛物线", raw):
        return None
    s = math_normalize(text)
    x = sym("x")
    steps: list[str] = []
    fe = _func_expr(s)
    pts = _points(raw)
    expr: Any = None
    if fe and set(letters_of(fe[0])) <= {"x"}:
        expr = sp.expand(fe[1])
        steps.append(f"y = {fmt(fe[1])}")
    elif len(pts) >= 3 and re.search(r"经过|过点|图象过", raw):
        a, b, c = sym("a"), sym("b"), sym("c")
        eqs = [a * px**2 + b * px + c - py for _, px, py in pts[:3]]
        sol = sp.solve(eqs, [a, b, c], dict=True)
        if len(sol) != 1 or sol[0].get(a, 0) == 0:
            return None
        expr = sp.expand(a * x**2 + b * x + c).subs(sol[0])
        steps.append("设 y = ax² + bx + c，把三个点的坐标代入得三元一次方程组：")
        steps += [f"{fmt(px**2)}a + {fmt(px)}b + c = {fmt(py)}" for _, px, py in pts[:3]]
        steps.append(f"解得 a = {fmt(sol[0][a])}，b = {fmt(sol[0][b])}，c = {fmt(sol[0][c])}，所以 y = {fmt(expr)}")
        for _, px, py in pts[:3]:
            if expr.subs(x, px) != py:
                return None
    else:
        return None
    p = sp.Poly(expr, x)
    if p.degree() != 2:
        return None
    a, b, c = p.all_coeffs()
    h = -b / (2 * a)
    k = c - b**2 / (4 * a)
    if sp.expand(a * (x - h) ** 2 + k - expr) != 0:
        return None
    asks = _ask_order(raw, {
        "vertex": r"顶点",
        "axis": r"对称轴",
        "xint": r"与\s*x\s*轴.{0,6}交点|与x轴的交点|零点",
        "yint": r"与\s*y\s*轴.{0,6}交点",
        "ext": r"最大值|最小值|最值",
        "dir": r"开口方向",
        "expr": r"解析式|表达式",
        "eval": r"当\s*x\s*=\s*-?\d",
    })
    if not asks:
        asks = ["vertex", "axis"]
    steps.append(f"配方：y = {fmt(a)}(x {'-' if h >= 0 else '+'} {fmt(abs(h))})² {'+' if k >= 0 else '-'} {fmt(abs(k))}".replace("= 1(", "= (").replace("= -1(", "= -("))
    vals: list[str] = []
    parts: list[str] = []
    for q in asks:
        if q == "vertex":
            steps.append(f"顶点坐标 (h, k) = (-b/2a, (4ac-b²)/4a) = ({fmt(h)}, {fmt(k)})")
            vals += [value_str(h), value_str(k)]
            parts.append(f"顶点 ({fmt(h)}, {fmt(k)})")
        elif q == "axis":
            steps.append(f"对称轴：直线 x = -b/(2a) = {fmt(h)}")
            vals.append(value_str(h))
            parts.append(f"对称轴 x = {fmt(h)}")
        elif q == "xint":
            rts = sorted([r for r in sp.solve(expr, x) if r.is_real], key=lambda r: float(r))
            disc = b**2 - 4 * a * c
            steps.append(f"令 y = 0：{fmt(expr)} = 0，Δ = {fmt(disc)}")
            if not rts:
                steps.append("Δ < 0，抛物线与 x 轴没有交点")
                parts.append("与 x 轴没有交点")
                vals.append("无")
                continue
            for r in rts:
                if sp.simplify(expr.subs(x, r)) != 0:
                    return None
            steps.append("解得 " + "，".join(f"x = {fmt(r)}" for r in rts))
            parts.append("与 x 轴交于 " + "、".join(f"({fmt(r)}, 0)" for r in rts))
            vals += [value_str(r) for r in rts]
        elif q == "yint":
            steps.append(f"令 x = 0，y = {fmt(c)}")
            parts.append(f"与 y 轴交于 (0, {fmt(c)})")
            vals += ["0", value_str(c)]
        elif q == "ext":
            word = "最小值" if a > 0 else "最大值"
            steps.append(f"a = {fmt(a)} {'>' if a > 0 else '<'} 0，开口向{'上' if a > 0 else '下'}，当 x = {fmt(h)} 时 y 有{word} {fmt(k)}")
            parts.append(f"当 x = {fmt(h)} 时，{word}为 {fmt(k)}")
            vals.append(value_str(k))
        elif q == "dir":
            parts.append(f"开口向{'上' if a > 0 else '下'}")
            vals.append("上" if a > 0 else "下")
        elif q == "expr":
            parts.append(f"y = {fmt(expr)}")
            vals.append(value_str(expr))
        elif q == "eval":
            m = re.search(r"当\s*x\s*=\s*(-?\d+(?:\.\d+)?(?:/\d+)?)", raw)
            assert m
            xv = sp.Rational(m.group(1))
            yv = expr.subs(x, xv)
            steps.append(f"当 x = {fmt(xv)} 时，y = {fmt(yv)}")
            parts.append(f"y = {fmt(yv)}")
            vals.append(value_str(yv))
    return KernelSolution(
        kernel="function.quadratic",
        answer="；".join(parts),
        steps=steps,
        hint="把解析式配方成 y = a(x-h)²+k：顶点 (h,k)、对称轴 x = h；a>0 开口向上有最小值，a<0 开口向下有最大值；与 x 轴交点令 y=0。",
        explanation="二次函数的图象与性质。",
        answer_value=", ".join(vals),
        answer_kind="nums" if len(vals) > 1 else ("expr" if asks == ["expr"] else "num"),
        check="顶点式展开与原式恒等；交点代入为 0",
    )


def solve_inverse_proportion(text: str) -> Optional[KernelSolution]:
    import sympy as sp

    raw = basic_normalize(text)
    if not re.search(r"反比例", raw):
        return None
    pts = _points(raw)
    steps: list[str] = []
    kv = None
    m_k = re.search(r"y\s*=\s*(-?\d+(?:\.\d+)?)\s*/\s*x", raw)
    if m_k:
        kv = sp.Rational(m_k.group(1))
        steps.append(f"y = {fmt(kv)}/x，k = {fmt(kv)}")
    elif pts:
        _, x0, y0 = pts[0]
        kv = x0 * y0
        steps.append(f"设 y = k/x，把 ({fmt(x0)}, {fmt(y0)}) 代入：k = xy = {fmt(x0)}×{fmt(y0)} = {fmt(kv)}")
    else:
        m = re.search(r"当\s*x\s*=\s*(-?\d+(?:\.\d+)?)\s*时\s*,?\s*y\s*=\s*(-?\d+(?:\.\d+)?)", raw)
        if not m:
            return None
        x0, y0 = sp.Rational(m.group(1)), sp.Rational(m.group(2))
        kv = x0 * y0
        steps.append(f"设 y = k/x，由 x = {fmt(x0)} 时 y = {fmt(y0)}，得 k = {fmt(x0)}×{fmt(y0)} = {fmt(kv)}")
    if kv == 0:
        return None
    vals, parts = [], []
    rest = raw[m_k.end():] if m_k else raw
    later = re.findall(r"当\s*x\s*=\s*(-?\d+(?:\.\d+)?)\s*时\s*,?\s*(?:求\s*)?y\s*(?:的值|=\s*\?|是多少|等于多少|为多少)", rest)
    later_y = re.findall(r"当\s*y\s*=\s*(-?\d+(?:\.\d+)?)\s*时\s*,?\s*(?:求\s*)?x", rest)
    if re.search(r"k\s*的值|求\s*k|解析式|表达式", raw):
        parts.append(f"k = {fmt(kv)}，y = {fmt(kv)}/x")
        vals.append(value_str(kv))
    for xs in later:
        xv = sp.Rational(xs)
        if xv == 0:
            return None
        yv = kv / xv
        steps.append(f"当 x = {fmt(xv)} 时，y = {fmt(kv)}/{fmt(xv)} = {fmt(yv)}")
        parts.append(f"y = {fmt(yv)}")
        vals.append(value_str(yv))
    for ys in later_y:
        yv = sp.Rational(ys)
        if yv == 0:
            return None
        xv = kv / yv
        steps.append(f"当 y = {fmt(yv)} 时，x = {fmt(kv)}/{fmt(yv)} = {fmt(xv)}")
        parts.append(f"x = {fmt(xv)}")
        vals.append(value_str(xv))
    if re.search(r"象限", raw):
        q = "一、三" if kv > 0 else "二、四"
        steps.append(f"k {'>' if kv > 0 else '<'} 0，图象在第{q}象限")
        parts.append(f"图象在第{q}象限")
    if not parts:
        return None
    return KernelSolution(
        kernel="function.inverse",
        answer="；".join(parts),
        steps=steps,
        hint="反比例函数 y = k/x 上每个点都满足 xy = k：先用已知点求 k，再代入求值。",
        explanation="反比例函数：k = xy。",
        answer_value=", ".join(vals),
        answer_kind="nums" if len(vals) > 1 else "num",
        check="已知点满足 xy = k",
    )


__all__ = ["solve_inverse_proportion", "solve_linear_function", "solve_quadratic_function"]
