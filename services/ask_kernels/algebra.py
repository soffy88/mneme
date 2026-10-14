"""代数内核：方程（一次/二次/分式/绝对值/含参数的二次）、不等式（组）、方程组、整式与分式运算。

每个解都经过验证：方程代回原方程；不等式在端点两侧取检验点；方程组代入每个方程；
展开/因式分解/化简检验与原式恒等（展开后相减为 0）。
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Any, Optional

from services.ask_kernels.core import KernelSolution, basic_normalize
from services.ask_kernels.sym import fmt, letters_of, math_normalize, parse, segments, split_relation, sym, value_str

_VARS = "xyzabmnt"


def disp(expr_str: str) -> str:
    s = expr_str.replace("*", "·").replace("sqrt", "√").replace("pi", "π")
    s = re.sub(r"(\d)·([a-z(√])", r"\1\2", s)
    s = re.sub(r"abs\(([^()]*)\)", r"|\1|", s)
    return s


def pf(v: Any) -> str:
    """负数加括号的格式化。"""
    t = fmt(v)
    return f"({t})" if t.startswith("-") else t


def _poly(expr: Any, v: Any) -> Any:
    import sympy as sp

    try:
        return sp.Poly(sp.expand(expr), v)
    except sp.PolynomialError:
        return None


def _rat(x: Any) -> Fraction:
    return Fraction(int(x.p), int(x.q))


def _has_denominator_var(expr_s: str) -> bool:
    return bool(re.search(r"/\s*\(?[^=]*[a-z]", expr_s))


# ── 一元方程 ─────────────────────────────────────────────────────────────────


def _linear_steps(lhs: Any, rhs: Any, v: Any) -> tuple[list[str], Any]:
    import sympy as sp

    steps: list[str] = []
    dens = [sp.fraction(sp.together(t))[1] for t in sp.Add.make_args(sp.expand(lhs)) + sp.Add.make_args(sp.expand(rhs))]
    lcd = sp.Integer(1)
    for d in dens:
        if d.is_number:
            lcd = sp.lcm(lcd, d)
    L, R = lhs, rhs
    if lcd != 1:
        L, R = sp.expand(lhs * lcd), sp.expand(rhs * lcd)
        steps.append(f"去分母（两边同乘 {fmt(lcd)}）：{fmt(L)} = {fmt(R)}")
    else:
        L, R = sp.expand(lhs), sp.expand(rhs)
        if (L, R) != (lhs, rhs) and (fmt(L) != fmt(lhs) or fmt(R) != fmt(rhs)):
            steps.append(f"去括号：{fmt(L)} = {fmt(R)}")
    p = sp.Poly(L - R, v)
    a, b = p.all_coeffs()
    steps.append(f"移项、合并同类项：{fmt(a * v)} = {fmt(-b)}")
    root = -b / a
    if a != 1:
        steps.append(f"系数化为 1（两边同除以 {fmt(a)}）：{fmt(v)} = {fmt(root)}")
    return steps, root


def _check_line(lhs: Any, rhs: Any, v: Any, root: Any) -> Optional[str]:
    import sympy as sp

    lv = sp.nsimplify(sp.simplify(lhs.subs(v, root)))
    rv = sp.nsimplify(sp.simplify(rhs.subs(v, root)))
    if sp.simplify(lv - rv) != 0:
        return None
    return f"检验：{fmt(v)} = {fmt(root)} 时，左边 = {fmt(lv)}，右边 = {fmt(rv)}，左边 = 右边 ✓"


def solve_equation_1var(text: str) -> Optional[KernelSolution]:
    """一元一次/二次方程、分式方程（含增根检验）、绝对值方程。"""
    import sympy as sp

    raw = basic_normalize(text)
    s = math_normalize(text)
    if re.search(r"方程组|不等式|函数|≥|≤|[<>]|化简|求值|其中", raw):
        return None
    if re.search(r"关于\s*[a-z]\s*的", raw) and re.search(r"有.*根|实数根|求\s*[a-z]\s*的", raw) and len(set(re.findall(r"[a-z]", s.replace("sqrt", "")))) >= 2:
        return None  # 含参数的方程交给 solve_quadratic_param
    for seg in segments(s):
        if seg.count("=") != 1 or "," in seg or ";" in seg:
            continue
        lhs_s, rhs_s = (p.strip() for p in seg.split("=", 1))
        if not lhs_s or not rhs_s or rhs_s == "?":
            continue
        letters = letters_of(seg)
        if len(letters) != 1 or letters[0] not in _VARS:
            continue
        name = letters[0]
        if re.fullmatch(r"[a-z]", lhs_s) and re.fullmatch(r"-?[\d./]+", rhs_s):
            continue  # “x = 3”是已知条件不是方程
        try:
            lhs, rhs = parse(lhs_s, name), parse(rhs_s, name)
        except ValueError:
            continue
        v = sym(name)
        if lhs.has(sp.Abs) or rhs.has(sp.Abs):
            return _solve_abs_eq(lhs, rhs, v, seg)
        num, den = sp.fraction(sp.together(lhs - rhs))
        if den.has(v):
            return _solve_frac_eq(lhs, rhs, v, num, den)
        p = _poly(lhs - rhs, v)
        if p is None or p.degree() < 1 or p.degree() > 2:
            continue
        if p.degree() == 1:
            steps = [f"原方程：{fmt(lhs)} = {fmt(rhs)}"]
            st, root = _linear_steps(lhs, rhs, v)
            steps += st
            chk = _check_line(lhs, rhs, v, root)
            if chk is None:
                return None
            steps.append(chk)
            return KernelSolution(
                kernel="algebra.linear_eq",
                answer=f"{name} = {fmt(root)}",
                steps=steps,
                hint=f"有分母先去分母，有括号先去括号；把含 {name} 的项移到左边、常数移到右边（移项要变号），再把系数化成 1。",
                explanation="一元一次方程：去分母、去括号、移项、合并同类项、系数化为 1，最后代回检验。",
                answer_value=f"{name}={value_str(root)}",
                answer_kind="nums",
                check="代入原方程两边相等",
            )
        return _solve_quadratic(lhs, rhs, v, raw)
    return None


def _solve_quadratic(lhs: Any, rhs: Any, v: Any, raw: str) -> Optional[KernelSolution]:
    import sympy as sp

    name = v.name
    expr = sp.expand(lhs - rhs)
    p = sp.Poly(expr, v)
    a, b, c = p.all_coeffs()
    steps = [f"原方程：{fmt(lhs)} = {fmt(rhs)}"]
    if sp.expand(lhs - rhs) != lhs or rhs != 0:
        steps.append(f"整理成一般形式：{fmt(expr)} = 0")
    disc = sp.simplify(b**2 - 4 * a * c)
    roots = sorted(set(sp.solve(sp.Eq(expr, 0), v)), key=lambda r: float(sp.re(r)) if r.is_real else 0)
    real_roots = [r for r in roots if r.is_real]
    method = "formula"
    if b == 0 and (-c / a) >= 0:
        method = "sqrt"
        steps.append(f"直接开平方：{name}^2 = {fmt(-c / a)}，所以 {name} = ±{fmt(sp.sqrt(-c / a))}")
    else:
        fac = sp.factor(expr)
        if isinstance(fac, sp.Mul) or (isinstance(fac, sp.Pow) and fac.exp == 2):
            if all(r.is_Rational for r in real_roots) and real_roots:
                method = "factor"
                steps.append(f"因式分解：{fmt(fac)} = 0")
                steps.append("两个因式的积为 0，至少有一个因式为 0")
        if method == "formula":
            steps.append(f"a = {fmt(a)}，b = {fmt(b)}，c = {fmt(c)}")
            steps.append(f"判别式 Δ = b² - 4ac = {pf(b)}² - 4×{pf(a)}×{pf(c)} = {fmt(disc)}")
            if disc < 0:
                steps.append("Δ < 0，方程没有实数根")
                return KernelSolution(
                    kernel="algebra.quadratic_eq",
                    answer="方程没有实数根",
                    steps=steps,
                    hint="先整理成 ax²+bx+c=0，再算判别式 Δ = b²-4ac 判断根的情况。",
                    explanation="一元二次方程：Δ<0 时没有实数根。",
                    answer_value="无实数根",
                    answer_kind="text",
                    check="Δ<0",
                )
            steps.append(f"用求根公式 {name} = (-b ± √Δ) / (2a) = ({fmt(-b)} ± √{fmt(disc)}) / {fmt(2 * a)}")
    if not real_roots:
        return None
    for r in real_roots:
        if sp.simplify(expr.subs(v, r)) != 0:
            return None
    real_roots = [sp.together(r) if not r.is_Rational else r for r in real_roots]
    if len(real_roots) == 1:
        ans = f"{name}₁ = {name}₂ = {fmt(real_roots[0])}"
    else:
        ans = f"{name}₁ = {fmt(real_roots[0])}，{name}₂ = {fmt(real_roots[1])}"
    steps.append(f"所以 {ans}")
    steps.append("检验：把每个根代入原方程，左右两边相等 ✓")
    return KernelSolution(
        kernel="algebra.quadratic_eq",
        answer=ans,
        steps=steps,
        hint="先整理成 ax²+bx+c=0：缺一次项可直接开平方；能因式分解（十字相乘）就分解；否则用求根公式（先算 Δ = b²-4ac）。",
        explanation="一元二次方程：直接开平方法、因式分解法、公式法。",
        answer_value=", ".join(value_str(r) for r in real_roots),
        answer_kind="nums",
        check="每个根代入原方程成立",
    )


def _solve_frac_eq(lhs: Any, rhs: Any, v: Any, num: Any, den: Any) -> Optional[KernelSolution]:
    import sympy as sp

    name = v.name
    dens = set()
    for side in (lhs, rhs):
        for t in sp.Add.make_args(sp.expand(side, deep=False)):
            d = sp.fraction(sp.together(t))[1]
            if d.has(v):
                dens.add(sp.factor(d))
    lcd = sp.factor(den)
    steps = [f"原方程：{fmt(lhs)} = {fmt(rhs)}"]
    steps.append(f"最简公分母是 {fmt(lcd)}，两边同乘它去分母")
    L = sp.expand(sp.cancel(lhs * lcd))
    R = sp.expand(sp.cancel(rhs * lcd))
    steps.append(f"得整式方程：{fmt(L)} = {fmt(R)}")
    p = _poly(L - R, v)
    if p is None or p.degree() > 2:
        return None
    if p.degree() < 1:
        if sp.expand(L - R) == 0:
            return None  # 恒等式：除使分母为 0 的值外都成立，不按常规题作答
        steps.append(f"整理得 {fmt(sp.expand(L - R))} = 0，矛盾，整式方程无解")
        steps.append("所以原分式方程无解")
        return KernelSolution(
            kernel="algebra.fractional_eq", answer="原方程无解", steps=steps,
            hint="两边同乘最简公分母化成整式方程；整式方程无解或解是增根时，原方程无解。",
            explanation="分式方程：去分母化整式方程 → 解 → 检验增根。", answer_value="无解", answer_kind="text",
            check="整式方程化简为矛盾等式",
        )
    cands = sorted({r for r in sp.solve(sp.Eq(L, R), v) if r.is_real}, key=lambda r: float(r))
    if not cands:
        return None
    steps.append("解这个整式方程：" + "，".join(f"{name} = {fmt(r)}" for r in cands))
    good, bad = [], []
    for r in cands:
        if sp.simplify(lcd.subs(v, r)) == 0:
            bad.append(r)
            steps.append(f"检验：{name} = {fmt(r)} 时，最简公分母 {fmt(lcd)} = 0，所以 {name} = {fmt(r)} 是增根，舍去")
        else:
            lv, rv = sp.simplify(lhs.subs(v, r)), sp.simplify(rhs.subs(v, r))
            if sp.simplify(lv - rv) != 0:
                return None
            good.append(r)
            steps.append(f"检验：{name} = {fmt(r)} 时，最简公分母 ≠ 0，且左边 = {fmt(lv)} = 右边 ✓")
    if not good:
        steps.append("所以原分式方程无解")
        ans, val, kind = "原方程无解（有增根）", "无解", "text"
    else:
        ans = "，".join(f"{name} = {fmt(r)}" for r in good)
        steps.append(f"所以原方程的解是 {ans}")
        val, kind = ", ".join(f"{value_str(r)}" for r in good), "nums"
        if len(good) == 1:
            val = f"{name}={value_str(good[0])}"
    return KernelSolution(
        kernel="algebra.fractional_eq",
        answer=ans,
        steps=steps,
        hint="两边同乘最简公分母化成整式方程；解出来一定要检验：使最简公分母为 0 的是增根，要舍去。",
        explanation="分式方程：去分母化整式方程 → 解 → 检验增根。",
        answer_value=val,
        answer_kind=kind,
        check="代入原方程，并检验最简公分母不为 0",
    )


def _solve_abs_eq(lhs: Any, rhs: Any, v: Any, seg: str) -> Optional[KernelSolution]:
    import sympy as sp

    name = v.name
    abs_terms = list(lhs.atoms(sp.Abs) | rhs.atoms(sp.Abs))
    if len(abs_terms) != 1:
        return None
    A = abs_terms[0]
    inner = A.args[0]
    if _poly(inner, v) is None or sp.Poly(inner, v).degree() != 1:
        return None
    steps = [f"原方程：{fmt(lhs)} = {fmt(rhs)}"]
    sols = []
    for sign, cond in ((1, "≥ 0"), (-1, "< 0")):
        L, R = lhs.subs(A, sign * inner), rhs.subs(A, sign * inner)
        p = _poly(L - R, v)
        if p is None or p.degree() != 1:
            if p is not None and p.degree() == 0 and sp.simplify(L - R) != 0:
                steps.append(f"当 {fmt(inner)} {cond} 时：方程化为 {fmt(L)} = {fmt(R)}，不成立")
                continue
            return None
        r = sp.solve(sp.Eq(L, R), v)[0]
        ok = (inner.subs(v, r) >= 0) if sign == 1 else (inner.subs(v, r) < 0)
        steps.append(f"当 {fmt(inner)} {cond} 时：{fmt(L)} = {fmt(R)}，得 {name} = {fmt(r)}" + ("，符合" if ok else "，不符合条件，舍去"))
        if ok:
            sols.append(r)
    sols = sorted(set(sols), key=lambda r: float(r))
    for r in sols:
        if sp.simplify(lhs.subs(v, r) - rhs.subs(v, r)) != 0:
            return None
    if not sols:
        ans, val, kind = "方程无解", "无解", "text"
    else:
        ans = "，".join(f"{name} = {fmt(r)}" for r in sols)
        val, kind = ", ".join(value_str(r) for r in sols), "nums"
    steps.append(f"所以 {ans}")
    return KernelSolution(
        kernel="algebra.abs_eq",
        answer=ans,
        steps=steps,
        hint="绝对值里面的式子分“≥0”和“<0”两种情况去掉绝对值，解完要看是否符合所设条件。",
        explanation="含绝对值的方程：分类讨论去绝对值。",
        answer_value=val,
        answer_kind=kind,
        check="每个解代入原方程成立",
    )


# ── 含参数的一元二次方程（判别式 / 已知一根） + 韦达定理 ─────────────────────────


_COND = [
    (r"两个不相等的实数根|两个不等实根|两个不相等实根", ">"),
    (r"两个相等的实数根|两个相等实根|有两个相等的根", "="),
    (r"没有实数根|无实数根|无实根", "<"),
    (r"有实数根|有两个实数根|有实根", "≥"),
]


def solve_quadratic_param(text: str) -> Optional[KernelSolution]:
    """关于 x 的方程 x²-2x+m=0 有两个相等的实数根，求 m；或已知一个根求参数和另一根。"""
    import sympy as sp

    raw = basic_normalize(text)
    m_var = re.search(r"关于\s*([a-z])\s*的", raw)
    if not m_var:
        return None
    vname = m_var.group(1)
    s = math_normalize(text)
    seg = next((g for g in segments(s) if g.count("=") == 1 and "," not in g), None)
    if seg is None:
        return None
    letters = letters_of(seg)
    params = [c for c in letters if c != vname]
    if vname not in letters or len(params) != 1:
        return None
    pname = params[0]
    lhs_s, rhs_s = seg.split("=", 1)
    try:
        expr = sp.expand(parse(lhs_s, vname + pname) - parse(rhs_s, vname + pname))
    except ValueError:
        return None
    v, k = sym(vname), sym(pname)
    p = _poly(expr, v)
    if p is None or p.degree() != 2:
        return None
    a, b, c = p.all_coeffs()
    if any(_poly(co, k) is None or sp.Poly(co, k).degree() > 2 for co in (a, b, c)):
        return None
    steps = [f"方程：{fmt(expr)} = 0（关于 {vname} 的一元二次方程）"]
    root_m = re.search(rf"(?:一个根是|一个根为|有一个根是|的一个根为|的一个根是|{vname}\s*=\s*)(-?\d+(?:\.\d+)?)\s*(?:是|为)?", raw)
    cond_op = next((op for pat, op in _COND if re.search(pat, raw)), None)
    if root_m and re.search(r"根", raw) and cond_op is None:
        r0 = sp.Rational(root_m.group(1))
        eq = sp.expand(expr.subs(v, r0))
        ks = [x for x in sp.solve(eq, k) if x.is_real and sp.simplify(a.subs(k, x)) != 0]
        if len(ks) != 1:
            return None
        kv = ks[0]
        steps.append(f"把 {vname} = {fmt(r0)} 代入方程：{fmt(eq)} = 0，解得 {pname} = {fmt(kv)}")
        full = sp.expand(expr.subs(k, kv))
        other = [r for r in sp.solve(full, v) if r.is_real]
        if not other:
            return None
        other_r = [r for r in other if r != r0] or [r0]
        steps.append(f"此时方程为 {fmt(full)} = 0，由两根之积 {vname}₁·{vname}₂ = c/a 得另一个根为 {fmt(other_r[0])}")
        if sp.simplify(full.subs(v, r0)) != 0 or sp.simplify(full.subs(v, other_r[0])) != 0:
            return None
        return KernelSolution(
            kernel="algebra.quadratic_param",
            answer=f"{pname} = {fmt(kv)}，另一个根是 {fmt(other_r[0])}",
            steps=steps,
            hint="方程的根一定满足方程：把已知的根代入，先求出参数，再求另一个根（或用根与系数的关系）。",
            explanation="一元二次方程的根的定义 + 根与系数的关系。",
            answer_value=f"{value_str(kv)}, {value_str(other_r[0])}",
            answer_kind="nums",
            check="两个根都代入方程成立",
        )
    if cond_op is None:
        return None
    disc = sp.expand(b**2 - 4 * a * c)
    steps.append(f"a = {fmt(a)}，b = {fmt(b)}，c = {fmt(c)}，Δ = b² - 4ac = {fmt(disc)}")
    need_a = a.has(k)
    rel = {">": sp.Gt, "=": sp.Eq, "<": sp.Lt, "≥": sp.Ge}[cond_op]
    word = {">": "Δ > 0", "=": "Δ = 0", "<": "Δ < 0", "≥": "Δ ≥ 0"}[cond_op]
    steps.append(f"根据题意 {word}：{fmt(disc)} {cond_op if cond_op != '≥' else '≥'} 0")
    if cond_op == "=":
        sols = [x for x in sp.solve(sp.Eq(disc, 0), k) if x.is_real]
        if need_a:
            sols = [x for x in sols if sp.simplify(a.subs(k, x)) != 0]
        if not sols:
            return None
        ans = "，".join(f"{pname} = {fmt(x)}" for x in sols)
        steps.append(f"解得 {ans}" + ("（且二次项系数不为 0）" if need_a else ""))
        for x in sols:
            if sp.simplify(disc.subs(k, x)) != 0:
                return None
        val, kind = ", ".join(value_str(x) for x in sols), "nums"
    else:
        if _poly(disc, k) is None or sp.Poly(disc, k).degree() != 1:
            return None
        sol = sp.solve_univariate_inequality(rel(disc, 0), k, relational=False)
        ineq = _interval_to_ineq(sol, pname)
        if ineq is None:
            return None
        if need_a:
            zero = [x for x in sp.solve(a, k) if x.is_real]
            for z in zero:
                if sol.contains(z) == sp.true:
                    ineq += f" 且 {pname} ≠ {fmt(z)}"
                    steps.append(f"又因为是一元二次方程，二次项系数 {fmt(a)} ≠ 0，所以 {pname} ≠ {fmt(z)}")
        ans = ineq
        steps.append(f"解得 {ineq}")
        val, kind = ineq.replace("≤", "<=").replace("≥", ">=").replace(" ", ""), "ineq"
        m_int = re.search(r"最(大|小)(?:的)?(?:正)?整数", raw)
        if m_int:
            excl = [x for x in (sp.solve(a, k) if need_a else []) if x.is_real]
            cands = []
            lo_b = sol.start if isinstance(sol, sp.Interval) else -sp.oo
            hi_b = sol.end if isinstance(sol, sp.Interval) else sp.oo
            if m_int.group(1) == "大" and hi_b != sp.oo:
                x0 = sp.floor(hi_b)
                for i in range(int(x0), int(x0) - 6, -1):
                    if sol.contains(i) == sp.true and i not in excl:
                        cands.append(i)
                        break
            elif m_int.group(1) == "小" and lo_b != -sp.oo:
                x0 = sp.ceiling(lo_b)
                for i in range(int(x0), int(x0) + 6):
                    if sol.contains(i) == sp.true and i not in excl:
                        cands.append(i)
                        break
            if not cands:
                return None
            steps.append(f"在 {ineq} 中，最{m_int.group(1)}的整数是 {cands[0]}")
            ans, val, kind = f"{pname} = {cands[0]}", str(cands[0]), "num"
    return KernelSolution(
        kernel="algebra.quadratic_param",
        answer=ans,
        steps=steps,
        hint="根的情况看判别式：Δ>0 两个不等实根，Δ=0 两个相等实根，Δ<0 没有实根；别忘了二次项系数不能为 0。",
        explanation="一元二次方程根的判别式。",
        answer_value=val,
        answer_kind=kind,
        check="把参数代回判别式验证符号",
    )


def _interval_to_ineq(sol: Any, name: str) -> Optional[str]:
    import sympy as sp

    if isinstance(sol, sp.Interval):
        lo, hi = sol.start, sol.end
        lo_s = "" if lo == -sp.oo else f"{fmt(lo)} {'<' if sol.left_open else '≤'} "
        hi_s = "" if hi == sp.oo else f" {'<' if sol.right_open else '≤'} {fmt(hi)}"
        if lo == -sp.oo and hi == sp.oo:
            return "全体实数"
        if lo == -sp.oo:
            return f"{name}{hi_s}"
        if hi == sp.oo:
            return f"{name} {'>' if sol.left_open else '≥'} {fmt(lo)}"
        return f"{lo_s}{name}{hi_s}"
    if sol == sp.S.EmptySet:
        return "无解"
    return None


def solve_vieta(text: str) -> Optional[KernelSolution]:
    """已知方程，求 x1+x2、x1x2、1/x1+1/x2、x1²+x2²、(x1-x2)²、|x1-x2| 或判断根的情况。"""
    import sympy as sp

    raw = basic_normalize(text)
    want_case = bool(re.search(r"根的情况|判断.*根|判别式", raw))
    want_vieta = bool(re.search(r"[a-z]\s*1|[a-z]₁|两根之和|两根之积|两根的和|两根的积|两个根的和|两个根的积|根与系数", raw))
    if not (want_case or want_vieta):
        return None
    s = math_normalize(re.sub(r"[a-z]\s*[12]", " ", raw.split("则")[0].split("求")[0]))
    seg = next((g for g in segments(s) if g.count("=") == 1 and "," not in g and len(letters_of(g)) == 1), None)
    if seg is None:
        return None
    name = letters_of(seg)[0]
    try:
        lhs, rhs = (parse(p, name) for p in seg.split("=", 1))
    except ValueError:
        return None
    v = sym(name)
    expr = sp.expand(lhs - rhs)
    p = _poly(expr, v)
    if p is None or p.degree() != 2:
        return None
    a, b, c = p.all_coeffs()
    disc = b**2 - 4 * a * c
    steps = [f"方程整理为 {fmt(expr)} = 0，a = {fmt(a)}，b = {fmt(b)}，c = {fmt(c)}"]
    steps.append(f"Δ = b² - 4ac = {fmt(disc)}")
    if want_case and not want_vieta:
        if disc > 0:
            ans, val = "方程有两个不相等的实数根", "两个不相等的实数根"
        elif disc == 0:
            ans, val = "方程有两个相等的实数根", "两个相等的实数根"
        else:
            ans, val = "方程没有实数根", "无实数根"
        steps.append(f"Δ {'>' if disc > 0 else ('=' if disc == 0 else '<')} 0，所以{ans}")
        return KernelSolution(
            kernel="algebra.discriminant",
            answer=ans,
            steps=steps,
            hint="根的情况看 Δ = b²-4ac 的符号。",
            explanation="一元二次方程根的判别式。",
            answer_value=val,
            answer_kind="text",
            check="判别式符号",
        )
    if disc < 0:
        return None
    S, P = -b / a, c / a
    steps.append(f"根据根与系数的关系：{name}₁ + {name}₂ = -b/a = {fmt(S)}，{name}₁·{name}₂ = c/a = {fmt(P)}")
    asks: list[tuple[int, str, Any, str]] = []
    q = raw[max(raw.find("则"), raw.find("求"), 0):]
    pats = [
        (r"1\s*/\s*[a-z]\s*1\s*\+\s*1\s*/\s*[a-z]\s*2|1/[a-z]₁\s*\+\s*1/[a-z]₂", S / P if P != 0 else None, "1/x₁ + 1/x₂ = (x₁+x₂)/(x₁x₂)"),
        (r"[a-z]\s*1\s*\^?\s*2\s*\+\s*[a-z]\s*2\s*\^?\s*2|[a-z]₁²\s*\+\s*[a-z]₂²|[a-z]1²\+[a-z]2²", S**2 - 2 * P, "x₁² + x₂² = (x₁+x₂)² - 2x₁x₂"),
        (r"\(\s*[a-z]\s*1\s*-\s*[a-z]\s*2\s*\)\s*\^?\s*2", S**2 - 4 * P, "(x₁-x₂)² = (x₁+x₂)² - 4x₁x₂"),
        (r"\|\s*[a-z]\s*1\s*-\s*[a-z]\s*2\s*\|", sp.sqrt(S**2 - 4 * P), "|x₁-x₂| = √[(x₁+x₂)² - 4x₁x₂]"),
        (r"(?<![/\d])[a-z]\s*1\s*\+\s*[a-z]\s*2(?!\s*\^|\s*2|²)|两根之和|两根的和|两个根的和", S, "x₁ + x₂ = -b/a"),
        (r"[a-z]\s*1\s*[·*×]?\s*[a-z]\s*2(?!\s*\^)|两根之积|两根的积|两个根的积", P, "x₁·x₂ = c/a"),
    ]
    taken: list[tuple[int, int]] = []
    qn = basic_normalize(q).replace("x₁", "x1").replace("x₂", "x2").replace("^2", "²")
    for pat, value, formula in pats:
        for m in re.finditer(pat, qn):
            if any(m.start() < e and m.end() > s0 for s0, e in taken) or value is None:
                continue
            taken.append((m.start(), m.end()))
            asks.append((m.start(), formula, value, m.group(0)))
    if not asks:
        return None
    asks.sort(key=lambda t: t[0])
    for _, formula, value, _g in asks:
        steps.append(f"{formula} = {fmt(sp.simplify(value))}")
    rts = sp.solve(expr, v)
    if len(rts) == 2:
        r1, r2 = rts
        if sp.simplify(r1 + r2 - S) != 0 or sp.simplify(r1 * r2 - P) != 0:
            return None
    vals = [sp.simplify(x[2]) for x in asks]
    return KernelSolution(
        kernel="algebra.vieta",
        answer="，".join(f"{x[3].strip()} = {fmt(val)}" for x, val in zip(asks, vals)),
        steps=steps,
        hint="不用求出两个根：先写出 x₁+x₂ = -b/a、x₁x₂ = c/a，再把要求的式子变形成只含和与积的形式。",
        explanation="一元二次方程根与系数的关系（韦达定理）。",
        answer_value=", ".join(value_str(x) for x in vals),
        answer_kind="nums" if len(vals) > 1 else "num",
        check="与直接求根的和、积一致",
    )


# ── 不等式（组） ─────────────────────────────────────────────────────────────

_FLIP = {"<": ">", ">": "<", "≤": "≥", "≥": "≤"}


def _ineq_parts(s: str) -> list[str]:
    s = s.replace("{", ",").replace("}", ",")
    parts = [p.strip() for p in re.split(r"[,;\n]|且|并且|和", s) if p.strip()]
    out = []
    for p in parts:
        # 连写不等式 a < 2x+1 ≤ b 拆两个
        ops = re.findall(r"≤|≥|<|>", p)
        if len(ops) == 2 and "=" not in p:
            m = re.match(r"(.+?)(≤|≥|<|>)(.+?)(≤|≥|<|>)(.+)", p)
            if m:
                out.append(f"{m.group(1)}{m.group(2)}{m.group(3)}")
                out.append(f"{m.group(3)}{m.group(4)}{m.group(5)}")
                continue
        out.append(p)
    return out


def _solve_one_ineq(part: str, name: str) -> Optional[tuple[str, Any, list[str]]]:
    import sympy as sp

    rel = split_relation(part)
    if rel is None or rel[1] not in _FLIP:
        return None
    lhs_s, op, rhs_s = rel
    lhs, rhs = parse(lhs_s, name), parse(rhs_s, name)
    v = sym(name)
    p = _poly(lhs - rhs, v)
    if p is None or p.degree() != 1:
        return None
    a, b = p.all_coeffs()
    steps = [f"解 {fmt(lhs)} {op} {fmt(rhs)}："]
    dens = [sp.fraction(sp.together(t))[1] for t in sp.Add.make_args(sp.expand(lhs)) + sp.Add.make_args(sp.expand(rhs))]
    lcd = sp.Integer(1)
    for d in dens:
        if d.is_number:
            lcd = sp.lcm(lcd, d)
    if lcd != 1:
        steps.append(f"  去分母（两边同乘 {fmt(lcd)}）：{fmt(sp.expand(lhs * lcd))} {op} {fmt(sp.expand(rhs * lcd))}")
    steps.append(f"  移项、合并：{fmt(a * v)} {op} {fmt(-b)}")
    bound = -b / a
    op2 = op if a > 0 else _FLIP[op]
    if a != 1:
        steps.append(f"  两边同除以 {fmt(a)}" + ("（除以负数，不等号方向改变）" if a < 0 else "") + f"：{name} {op2} {fmt(bound)}")
    # 检验：边界两侧各取一点
    for x in (bound - sp.Rational(1, 2), bound + sp.Rational(1, 2)):
        truth = bool({"<": sp.Lt, ">": sp.Gt, "≤": sp.Le, "≥": sp.Ge}[op](lhs.subs(v, x), rhs.subs(v, x)))
        expect = bool({"<": sp.Lt, ">": sp.Gt, "≤": sp.Le, "≥": sp.Ge}[op2](x, bound))
        if truth != expect:
            return None
    return op2, bound, steps


def solve_inequality(text: str) -> Optional[KernelSolution]:
    import sympy as sp

    raw = basic_normalize(text)
    s = math_normalize(text)
    if not re.search(r"[<>≤≥]", s):
        return None
    if not re.search(r"解|解集|取值范围|整数解|数轴", raw) or re.search(r"科学记数法|其中\s*1\s*≤", raw):
        return None
    # 题面里含不等号的片段
    cand = [g for g in segments(s) if re.search(r"[<>≤≥]", g)]
    if not cand:
        return None
    region = s
    first = s.find(cand[-1]) if cand else 0
    seg_text = ",".join(sorted(cand, key=lambda g: s.find(g)))
    del region, first
    parts = [p for p in _ineq_parts(seg_text) if re.search(r"[<>≤≥]", p)]
    if not parts or len(parts) > 4:
        return None
    letters = sorted({c for p in parts for c in letters_of(p)})
    if len(letters) != 1:
        return None
    name = letters[0]
    steps: list[str] = []
    bounds: list[tuple[str, Any]] = []
    for p in parts:
        try:
            r = _solve_one_ineq(p, name)
        except ValueError:
            return None
        if r is None:
            return None
        op2, bound, st = r
        steps += st
        bounds.append((op2, bound))
    # 交集
    lo, lo_incl, hi, hi_incl = -sp.oo, False, sp.oo, False
    for op, b in bounds:
        if op in (">", "≥"):
            if b > lo or (b == lo and op == ">"):
                lo, lo_incl = b, op == "≥"
        else:
            if b < hi or (b == hi and op == "<"):
                hi, hi_incl = b, op == "≤"
    empty = lo > hi or (lo == hi and not (lo_incl and hi_incl))
    if empty:
        ans, val = "不等式组无解", "无解"
    else:
        ans = _interval_text(name, lo, lo_incl, hi, hi_incl)
        val = ans.replace("≤", "<=").replace("≥", ">=").replace(" ", "")
    if len(bounds) > 1:
        steps.append("取各个不等式解集的公共部分（同大取大，同小取小，大小小大中间找，大大小小找不到）")
    steps.append(("所以解集为：" + ans) if not empty else "两个解集没有公共部分，所以不等式组无解")
    if not empty:
        steps.append("数轴表示：" + _number_line(lo, lo_incl, hi, hi_incl))
    kind = "ineq"
    answer = ans
    # 整数解
    m_int = re.search(r"(非负整数|正整数|负整数|整数)解", raw)
    if m_int and not empty:
        kind_w = m_int.group(1)
        if lo == -sp.oo and kind_w in ("整数", "负整数") and hi == sp.oo:
            return None
        start = sp.ceiling(lo) if lo != -sp.oo else None
        end = sp.floor(hi) if hi != sp.oo else None
        if kind_w == "正整数":
            start = max(start, 1) if start is not None else 1
        if kind_w == "非负整数":
            start = max(start, 0) if start is not None else 0
        if kind_w == "负整数":
            end = min(end, -1) if end is not None else -1
        if start is None or end is None:
            return None
        ints = [i for i in range(int(start), int(end) + 1)
                if (i > lo or (lo_incl and i == lo)) and (i < hi or (hi_incl and i == hi))]
        if len(ints) > 30:
            return None
        steps.append(f"其中的{kind_w}解有：" + ("、".join(str(i) for i in ints) if ints else "没有"))
        if re.search(r"个数|几个|多少个", raw):
            answer, val, kind = f"{len(ints)} 个（{'、'.join(map(str, ints))}）", str(len(ints)), "num"
        elif re.search(r"和", raw[m_int.end():]):
            answer, val, kind = f"{sum(ints)}", str(sum(ints)), "num"
        else:
            answer, val, kind = "、".join(map(str, ints)) or "没有", ", ".join(map(str, ints)), "nums"
    return KernelSolution(
        kernel="algebra.inequality_system" if len(bounds) > 1 else "algebra.inequality",
        answer=answer,
        steps=steps,
        hint="解法和方程一样，只是两边乘或除以负数时不等号要改变方向；不等式组取公共部分，画数轴最清楚。",
        explanation="一元一次不等式（组）：解每个不等式，再在数轴上取公共部分。",
        answer_value=val,
        answer_kind=kind,
        check="边界两侧取点代入原不等式检验",
    )


def _interval_text(name: str, lo: Any, lo_incl: bool, hi: Any, hi_incl: bool) -> str:
    import sympy as sp

    if lo == -sp.oo and hi == sp.oo:
        return "全体实数"
    if lo == -sp.oo:
        return f"{name} {'≤' if hi_incl else '<'} {fmt(hi)}"
    if hi == sp.oo:
        return f"{name} {'≥' if lo_incl else '>'} {fmt(lo)}"
    if lo == hi:
        return f"{name} = {fmt(lo)}"
    return f"{fmt(lo)} {'≤' if lo_incl else '<'} {name} {'≤' if hi_incl else '<'} {fmt(hi)}"


def _number_line(lo: Any, lo_incl: bool, hi: Any, hi_incl: bool) -> str:
    import sympy as sp

    parts = []
    if lo != -sp.oo:
        parts.append(f"在 {fmt(lo)} 处画{'实心点' if lo_incl else '空心圈'}")
    if hi != sp.oo:
        parts.append(f"在 {fmt(hi)} 处画{'实心点' if hi_incl else '空心圈'}")
    if lo == -sp.oo:
        parts.append("向左画")
    elif hi == sp.oo:
        parts.append("向右画")
    else:
        parts.append("两点之间的部分")
    return "，".join(parts)


# ── 二元/三元一次方程组 ───────────────────────────────────────────────────────


def solve_linear_system(text: str) -> Optional[KernelSolution]:
    import sympy as sp

    raw = basic_normalize(text)
    s = math_normalize(text).replace("{", ",").replace("}", ",")
    if re.search(r"[<>≤≥]", s):
        return None
    eqs_s = []
    for seg in sorted(segments(s), key=lambda g: s.find(g)):
        for p in re.split(r"[,;\n]", seg):
            p = p.strip()
            if p.count("=") == 1 and all(x.strip() for x in p.split("=")):
                eqs_s.append(p)
    if len(eqs_s) < 2 or len(eqs_s) > 3:
        return None
    if re.search(r"化简|求值|其中", raw) or all(re.fullmatch(r"\s*[a-z]\s*=\s*-?[\d./]+\s*", e) for e in eqs_s):
        return None
    letters = sorted({c for e in eqs_s for c in letters_of(e)})
    if len(letters) != len(eqs_s) or any(c not in _VARS for c in letters):
        return None
    if not re.search(r"方程组|解方程|解下列|求.*的值|\{", raw + text) and len(eqs_s) < 2:
        return None
    syms = [sym(c) for c in letters]
    eqs = []
    for e in eqs_s:
        lhs_s, rhs_s = e.split("=", 1)
        try:
            ex = sp.expand(parse(lhs_s, "".join(letters)) - parse(rhs_s, "".join(letters)))
        except ValueError:
            return None
        p = sp.Poly(ex, *syms) if ex.free_symbols else None
        if p is None or p.total_degree() != 1:
            return None
        eqs.append(ex)
    sol = sp.solve(eqs, syms, dict=True)
    if len(sol) != 1 or len(sol[0]) != len(syms):
        return None
    sol0 = sol[0]
    for ex in eqs:
        if sp.simplify(ex.subs(sol0)) != 0:
            return None
    steps = ["方程组：" + "；".join(f"{fmt(ex)} = 0" if False else e.replace("*", "") for e in eqs_s)]
    steps += _elimination_steps(eqs, syms, sol0)
    ans = "，".join(f"{c} = {fmt(sol0[s_])}" for c, s_ in zip(letters, syms))
    steps.append(f"所以方程组的解是 {ans}")
    steps.append("检验：把解代入每个方程，左右两边都相等 ✓")
    return KernelSolution(
        kernel=f"algebra.linear_system_{len(syms)}",
        answer=ans,
        steps=steps,
        hint="用加减消元或代入消元：先把一个未知数消掉，变成一元一次方程。" + ("三元的先消去同一个未知数变成二元方程组。" if len(syms) == 3 else ""),
        explanation=f"{'二' if len(syms) == 2 else '三'}元一次方程组：消元。",
        answer_value=", ".join(f"{c}={value_str(sol0[s_])}" for c, s_ in zip(letters, syms)),
        answer_kind="nums",
        check="解代入每个方程成立",
    )


def _elimination_steps(eqs: list[Any], syms: list[Any], sol: dict) -> list[str]:
    import sympy as sp

    steps: list[str] = []
    if len(syms) == 2:
        x, y = syms
        e1, e2 = eqs
        a1, b1 = e1.coeff(x), e1.coeff(y)
        a2, b2 = e2.coeff(x), e2.coeff(y)
        # 消 y：①×|b2| ∓ ②×|b1|
        if b1 != 0 and b2 != 0:
            L = sp.lcm(abs(b1), abs(b2)) if b1.is_Integer and b2.is_Integer else abs(b1 * b2)
            k1, k2 = L / abs(b1), L / abs(b2)
            same_sign = (b1 > 0) == (b2 > 0)
            comb = sp.expand(k1 * e1 - k2 * e2) if same_sign else sp.expand(k1 * e1 + k2 * e2)
            how = f"①×{fmt(k1)} {'-' if same_sign else '+'} ②×{fmt(k2)}" if (k1 != 1 or k2 != 1) else f"① {'-' if same_sign else '+'} ②"
            steps.append(f"消去 {y.name}：{how}，得 {fmt(comb)} = 0")
            steps.append(f"解得 {x.name} = {fmt(sol[x])}")
            back = e1 if b1 != 0 else e2
            steps.append(f"把 {x.name} = {fmt(sol[x])} 代入①：{fmt(sp.expand(back.subs(x, sol[x])))} = 0，解得 {y.name} = {fmt(sol[y])}")
            del a1, a2
            return steps
        steps.append(f"由方程直接解得 {x.name} = {fmt(sol[x])}，{y.name} = {fmt(sol[y])}")
        return steps
    x, y, z = syms
    steps.append(f"把三个方程编号①②③，先消去 {z.name} 得到关于 {x.name}、{y.name} 的二元一次方程组")
    pairs = [(0, 1), (0, 2), (1, 2)]
    new = []
    for i, j in pairs:
        ci, cj = eqs[i].coeff(z), eqs[j].coeff(z)
        if ci == 0 and cj == 0:
            continue
        if ci == 0:
            comb = eqs[i]
        elif cj == 0:
            comb = eqs[j]
        else:
            comb = sp.expand(cj * eqs[i] - ci * eqs[j])
        if comb.coeff(z) == 0 and comb != 0 and comb not in new:
            new.append(comb)
            steps.append(f"由{'①②③'[i]}{'①②③'[j]}消 {z.name}：{fmt(comb)} = 0")
        if len(new) == 2:
            break
    steps.append(f"解这个二元一次方程组得 {x.name} = {fmt(sol[x])}，{y.name} = {fmt(sol[y])}")
    steps.append(f"代回求得 {z.name} = {fmt(sol[z])}")
    return steps


# ── 整式 / 分式：展开、因式分解、化简（求值）、配方 ─────────────────────────────


def _expr_segment(s: str, *, allow_eq: bool = False, first: bool = False) -> Optional[str]:
    segs = segments(s, need_digit=False)
    if first:
        segs = sorted(segs, key=lambda g: s.find(g))
    for seg in segs:
        e = seg.strip()
        if "=" in e and not allow_eq:
            left, right = e.split("=", 1)
            if right.strip() in {"", "?"}:
                e = left.strip()
            else:
                continue
        if re.search(r"[<>≤≥,;]", e):
            continue
        if not letters_of(e):
            continue
        return e
    return None


def _factor_method(expr: Any, fac: Any, v_syms: set) -> str:
    import sympy as sp

    methods = []
    coeff, rest = sp.factor_terms(expr).as_coeff_Mul()
    parts = sp.Mul.make_args(sp.factor_terms(expr))
    if len([f for f in parts if not f.is_number]) > 1 or (coeff != 1 and coeff != -1):
        methods.append("先提公因式")
    poly_part = [f for f in parts if isinstance(f, sp.Add)]
    target = poly_part[0] if poly_part else rest
    n_terms = len(sp.Add.make_args(sp.expand(target)))
    fs = sp.factor(target)
    if n_terms == 2:
        methods.append("再用平方差公式 a²-b² = (a+b)(a-b)")
    elif n_terms == 3 and isinstance(fs, sp.Pow):
        methods.append("再用完全平方公式 a²±2ab+b² = (a±b)²")
    elif n_terms == 3:
        methods.append("再用十字相乘法")
    elif n_terms >= 4:
        methods.append("分组分解")
    return "，".join(methods) if methods else "因式分解"


def solve_polynomial(text: str) -> Optional[KernelSolution]:
    import sympy as sp

    raw = basic_normalize(text)
    want_factor = bool(re.search(r"因式分解|分解因式", raw))
    want_square = bool(re.search(r"配方|顶点式|写成.*\(\s*[a-z]\s*[+-]", raw)) and not re.search(r"函数", raw)
    want_eval = re.search(r"(?:其中|当)\s*([a-z])\s*=\s*(-?\s*\d+(?:\.\d+)?(?:/\d+)?|-?√\d+|-?\d*√\d+)", raw)
    want_simplify = bool(re.search(r"化简|计算|展开|求值|先化简", raw))
    if not (want_factor or want_square or want_simplify):
        return None
    # 叙述型题（“小马虎在计算…时漏掉了括号，算成了…，相差多少”）：题面里有两个式子在比较，不是让你展开这一个
    if re.search(r"漏掉|漏了|算成|看成|抄错|抄成|相差|错误的结果|正确的结果|比较大小|差是多少", raw):
        return None
    if len([m for m in re.findall(r"\$([^$]+)\$", text or "") if re.search(r"[a-z]", re.sub(r"\\[a-zA-Z]+", "", m))]) > 1:
        return None
    head = raw
    if want_eval:
        head = raw[: want_eval.start()]
    hs = math_normalize(head)
    expr_s = _expr_segment(hs, first=want_square)
    if expr_s is None:
        return None
    letters = letters_of(expr_s)
    if len(letters) > 3:
        return None
    try:
        expr = parse(expr_s, "".join(letters))
    except ValueError:
        return None
    syms = sorted(expr.free_symbols, key=lambda x: x.name)
    if not syms:
        return None
    steps = [f"原式 = {disp(expr_s)}"]
    if want_factor:
        fac = sp.factor(expr)
        if fac == expr or not isinstance(fac, (sp.Mul, sp.Pow)):
            return None
        if sp.expand(fac - expr) != 0:
            return None
        method = _factor_method(expr, fac, set(syms))
        common = sp.factor_terms(expr)
        if isinstance(common, sp.Mul) and common != fac:
            steps.append(f"提公因式：= {fmt(common)}")
        steps.append(f"{method}：= {fmt(fac)}")
        steps.append("检验：把结果展开，等于原式 ✓")
        return KernelSolution(
            kernel="algebra.factor",
            answer=fmt(fac),
            steps=steps,
            hint="因式分解的顺序：一提（公因式）、二套（平方差、完全平方公式）、三查（每个因式还能不能再分解）。",
            explanation="因式分解：提公因式法、公式法、十字相乘法。",
            answer_value=value_str(fac),
            answer_kind="expr",
            check="展开后与原式恒等",
        )
    if want_square and len(syms) == 1:
        v = syms[0]
        p = _poly(expr, v)
        if p is None or p.degree() != 2:
            return None
        a, b, c = p.all_coeffs()
        h = -b / (2 * a)
        k = c - b**2 / (4 * a)
        vf = a * (v - h) ** 2 + k
        if sp.expand(vf - expr) != 0:
            return None
        steps.append(f"提出二次项系数：= {fmt(a)}({fmt(sp.expand(expr / a - c / a))}) + {fmt(c)}" if a != 1 else f"配方：加上并减去一次项系数一半的平方 ({fmt(b / 2)})²")
        steps.append(f"= {'' if a == 1 else ('-' if a == -1 else fmt(a))}({v.name} {'-' if h >= 0 else '+'} {fmt(abs(h))})² {'+' if k >= 0 else '-'} {fmt(abs(k))}")
        ans = f"{'' if a == 1 else ('-' if a == -1 else fmt(a))}({v.name} {'-' if h >= 0 else '+'} {fmt(abs(h))})² {'+' if k >= 0 else '-'} {fmt(abs(k))}"
        return KernelSolution(
            kernel="algebra.complete_square",
            answer=ans,
            steps=steps,
            hint="配方：先提二次项系数，再加上并减去一次项系数一半的平方。",
            explanation="配方法：ax²+bx+c = a(x-h)²+k。",
            answer_value=value_str(vf),
            answer_kind="expr",
            check="展开后与原式恒等",
        )
    # 化简（整式展开或分式约分/通分）
    is_rational = bool(sp.fraction(sp.together(expr))[1].free_symbols)
    if is_rational:
        simp = sp.factor(sp.cancel(sp.together(expr)))
        num, den = sp.fraction(sp.together(expr))
        steps.append(f"通分/把分子分母分别因式分解：= {fmt(sp.factor(num))} / ({fmt(sp.factor(den))})")
        steps.append(f"约去公因式：= {fmt(simp)}")
    else:
        simp = sp.expand(expr)
        if re.search(r"\)\s*\^?\s*2|\)\s*\(", expr_s):
            steps.append("用乘法公式/多项式乘法展开：(a±b)² = a²±2ab+b²，(a+b)(a-b) = a²-b²")
        steps.append(f"去括号、合并同类项：= {fmt(simp)}")
    if sp.simplify(simp - expr) != 0:
        return None
    if want_eval:
        assigns = re.findall(r"(?<![a-z])([a-z])\s*=\s*(-?\s*\d+(?:\.\d+)?(?:/\d+)?|-?√\d+|-?\d*√\d+)", raw[want_eval.start():])
        subs = {}
        for name, vtxt in assigns:
            try:
                subs[sym(name)] = parse(math_normalize(vtxt.replace(" ", "")))
            except ValueError:
                return None
        if set(subs) != set(syms):
            return None
        # 原式在该点必须有意义
        try:
            orig_v = sp.simplify(expr.subs(subs))
        except Exception:  # noqa: BLE001
            return None
        if orig_v.has(sp.zoo, sp.nan) or not orig_v.is_finite:
            return None
        res = sp.radsimp(sp.simplify(simp.subs(subs)))
        if sp.simplify(res - orig_v) != 0:
            return None
        cond = "，".join(f"{k.name} = {fmt(v)}" for k, v in subs.items())
        steps.append(f"当 {cond} 时，原式 = {fmt(res)}")
        return KernelSolution(
            kernel="algebra.simplify_eval",
            answer=fmt(res),
            steps=steps,
            hint="先化简（分式要因式分解后约分、通分），再把数值代入化简后的式子，计算量小得多。",
            explanation="先化简再求值。",
            answer_value=value_str(res),
            answer_kind="num",
            check="化简式与原式在该点取值相同",
        )
    return KernelSolution(
        kernel="algebra.simplify" if is_rational else "algebra.expand",
        answer=fmt(simp),
        steps=steps,
        hint="分式化简：分子分母先因式分解再约分；加减先通分。整式：用乘法公式去括号，再合并同类项。" if is_rational else "用乘法分配律和乘法公式去括号，再合并同类项。",
        explanation="分式的化简。" if is_rational else "整式的乘法与合并同类项。",
        answer_value=value_str(simp),
        answer_kind="expr",
        check="与原式恒等",
    )


__all__ = [
    "solve_equation_1var",
    "solve_inequality",
    "solve_linear_system",
    "solve_polynomial",
    "solve_quadratic_param",
    "solve_vieta",
]
