"""初中化学计算内核（无 LLM）：相对分子质量、元素质量分数/质量比/元素质量、溶液溶质质量分数与稀释、
根据化学方程式的质量计算（先用守恒矩阵配平，复用 oprim.chemical_equation）。

相对原子质量用初中教材取值（Cl=35.5 其余取整）。全部 Fraction 精确计算，结果按需保留到 0.1%。
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Optional

from services.ask_kernels.core import KernelSolution, basic_normalize, fmt_num, fmt_sig

F = Fraction

AR: dict[str, Fraction] = {
    "H": F(1), "He": F(4), "C": F(12), "N": F(14), "O": F(16), "F": F(19), "Ne": F(20), "Na": F(23), "Mg": F(24), "Al": F(27),
    "Si": F(28), "P": F(31), "S": F(32), "Cl": F(71, 2), "Ar": F(40), "K": F(39), "Ca": F(40), "Mn": F(55), "Fe": F(56),
    "Cu": F(64), "Zn": F(65), "Ag": F(108), "Ba": F(137), "I": F(127), "Hg": F(201), "Br": F(80), "Li": F(7), "Be": F(9), "B": F(11),
}
_EL_NAMES = {"氢": "H", "碳": "C", "氮": "N", "氧": "O", "钠": "Na", "镁": "Mg", "铝": "Al", "硅": "Si", "磷": "P", "硫": "S",
             "氯": "Cl", "钾": "K", "钙": "Ca", "锰": "Mn", "铁": "Fe", "铜": "Cu", "锌": "Zn", "银": "Ag", "钡": "Ba", "碘": "I", "氟": "F"}
_FORMULA = r"(?:\d*(?:[A-Z][a-z]?\d*|\([A-Za-z0-9]+\)\d*)+(?:[·*.]\d*(?:[A-Z][a-z]?\d*)+)?)"
_NAMES = {"水": "H2O", "二氧化碳": "CO2", "氧气": "O2", "氢气": "H2", "一氧化碳": "CO", "碳酸钙": "CaCO3", "氧化钙": "CaO",
          "氯化钠": "NaCl", "盐酸": "HCl", "氯化氢": "HCl", "硫酸": "H2SO4", "氢氧化钠": "NaOH", "高锰酸钾": "KMnO4",
          "氯酸钾": "KClO3", "过氧化氢": "H2O2", "双氧水": "H2O2", "甲烷": "CH4", "锌": "Zn", "铁": "Fe", "镁": "Mg", "铜": "Cu",
          "氧化铜": "CuO", "氧化铁": "Fe2O3", "四氧化三铁": "Fe3O4", "氯化钙": "CaCl2", "硫酸锌": "ZnSO4", "硫酸铜": "CuSO4",
          "氯化锌": "ZnCl2", "氯化镁": "MgCl2", "氧化镁": "MgO", "碳": "C", "硫酸亚铁": "FeSO4", "氯化亚铁": "FeCl2", "铝": "Al",
          "氧化铝": "Al2O3", "硝酸铵": "NH4NO3", "尿素": "CO(NH2)2", "碳酸氢铵": "NH4HCO3", "氨气": "NH3", "乙醇": "C2H5OH", "酒精": "C2H5OH",
          "葡萄糖": "C6H12O6", "碳酸钠": "Na2CO3", "氢氧化钙": "Ca(OH)2", "锰酸钾": "K2MnO4", "二氧化锰": "MnO2", "氯化钾": "KCl"}


def _parse(formula: str) -> Optional[dict[str, int]]:
    try:
        from oprim.chemical_equation import parse_formula

        pf = parse_formula(formula.replace("*", "·").replace(".", "·"))
        return dict(pf.counts)
    except Exception:  # noqa: BLE001
        return None


def _mr(counts: dict[str, int]) -> Optional[Fraction]:
    tot = F(0)
    for el, n in counts.items():
        if el not in AR:
            return None
        tot += AR[el] * n
    return tot


def _mr_steps(formula: str, counts: dict[str, int]) -> str:
    parts = [f"{fmt_num(AR[el])}×{n}" if n > 1 else fmt_num(AR[el]) for el, n in counts.items()]
    return f"Mr({formula}) = " + " + ".join(parts) + f" = {fmt_num(_mr(counts) or 0)}"


def _norm(text: str) -> str:
    s = basic_normalize(text)
    s = s.replace("•", "·").replace("・", "·")
    # 反应条件写在等号上：=MnO2=、=高温=、=△=、→(点燃)
    s = re.sub(r"=+\s*(?:MnO2|高温|点燃|△|加热|通电|催化剂|光照)\s*=+", " = ", s)
    s = re.sub(r"(?:→|->|⟶)\s*\(?\s*(?:点燃|高温|△|加热|通电|催化剂|MnO2)?\s*\)?", " = ", s)
    s = s.replace("___", " ").replace("__", " ")
    return s


def _strip_given(s: str) -> str:
    """去掉题目给出的相对原子/分子质量表“(H=1，O=16)”“CaCO3=100”，避免当成题目里的物质。"""
    s = re.sub(r"[(（][^()（）]*?[A-Z][a-z]?\d*\s*=\s*\d[^()（）]*[)）]", " ", s)
    # “(Ca-40 C-12 O-16)”“[H:1, O:16]”这类相对原子质量提示
    s = re.sub(r"[(（\[［][^()（）\[\]［］]*?[A-Z][a-z]?\s*[-—:：]\s*\d[^()（）\[\]［］]*[)）\]］]", " ", s)
    s = re.sub(r"(?:相对原子质量)?[:：]?\s*(?:(?<![A-Za-z])[A-Z][a-z]?\s*[-—:：]\s*\d+(?:\.\d+)?[\s,，、;；]*){2,}", " ", s)
    return re.sub(r"(?<![A-Za-z0-9])([A-Z][a-z]?\d*)+\s*=\s*\d+(?:\.\d+)?(?![\d.]*\s*(?:g|克|t|吨|kg))", " ", s)


def _formulas_in(s: str) -> list[str]:
    out = []
    for m in re.finditer(_FORMULA, s):
        f = m.group(0)
        if not re.search(r"[A-Z]", f):
            continue
        f = re.sub(r"^\d+", "", f)
        if _parse(f) is None:
            continue
        out.append(f)
    return out


def _pct(v: Fraction) -> str:
    x = v * 100
    s = fmt_num(x, max_dec=2)
    return s if "/" not in s else fmt_sig(x)


def _pct_val(v: Fraction) -> str:
    x = v * 100
    s = fmt_num(x, max_dec=4)
    return s if "/" not in s else f"{float(x):.4g}"


def _trust_names(s: str) -> str:
    """“葡萄糖C0H2O”：OCR 常丢化学式下标，但中文名可靠——名字后紧跟的化学式与名字对应的不一致时，换成名字的化学式。"""
    for name, canon in sorted(_NAMES.items(), key=lambda kv: -len(kv[0])):
        if len(name) < 2:
            continue
        want = _parse(canon)
        for m in re.finditer(rf"{name}\s*[(（]?\s*({_FORMULA})", s):
            got = _parse(re.sub(r"^\d+", "", m.group(1)))
            if want and got != want:
                s = s[:m.start(1)] + canon + s[m.end(1):]
                break
    return s


def solve_chemistry_calc(text: str) -> Optional[KernelSolution]:
    s = _trust_names(_norm(text))
    for fn in (_solve_stoich, _solve_solution, _solve_mass_fraction, _solve_mr):
        try:
            r = fn(s)
        except (ValueError, ZeroDivisionError):
            r = None
        if r is not None:
            return r
    return None


def _solve_mr(s: str) -> Optional[KernelSolution]:
    if not re.search(r"相对分子质量|相对分子量|式量|分子质量", s):
        return None
    s = _strip_given(s)
    fs = list(dict.fromkeys(_formulas_in(s)))
    if len(fs) != 1:
        return None
    f = fs[0]
    counts = _parse(f)
    if not counts:
        return None
    mr = _mr(counts)
    if mr is None:
        return None
    steps = ["相对分子质量 = 各原子的相对原子质量 × 原子个数之和", _mr_steps(f, counts)]
    mc = re.search(rf"(\d+)\s*{re.escape(f)}", s)
    if mc and int(mc.group(1)) > 1 and re.search(r"总和|总质量|之和", s):
        k = int(mc.group(1))
        steps.append(f"{k}{f} 的相对分子质量总和 = {k} × {fmt_num(mr)} = {fmt_num(k * mr)}")
        mr = k * mr
    return KernelSolution(kernel="chemistry.formula_mass", answer=f"{fmt_num(mr)}", steps=steps,
                          hint="把化学式里每种原子的相对原子质量乘以它的个数，再全部加起来（括号外的数字要乘进去）。",
                          explanation="相对分子质量的计算。", answer_value=fmt_num(mr, max_dec=4), answer_kind="num", unit="",
                          check="按元素逐项复算", confidence=0.95)


def _element_in(s: str) -> Optional[str]:
    m = re.search(r"([\u4e00-\u9fff])元素", s)
    if m and m.group(1) in _EL_NAMES:
        return _EL_NAMES[m.group(1)]
    m = re.search(r"(?<![A-Za-z])([A-Z][a-z]?)\s*(?:元素)?的?(?:质量分数|质量)", s)
    if m and m.group(1) in AR:
        return m.group(1)
    return None


def _solve_mass_fraction(s: str) -> Optional[KernelSolution]:
    if not re.search(r"元素|质量比", s):
        return None
    s = _strip_given(s)
    fs = list(dict.fromkeys(_formulas_in(s)))
    if len(fs) != 1:
        return None
    f = fs[0]
    counts = _parse(f)
    if not counts:
        return None
    mr = _mr(counts)
    if mr is None:
        return None
    steps = [_mr_steps(f, counts)]
    if re.search(r"质量比", s) and not re.search(r"质量分数", s):
        els = list(counts)
        parts = [AR[e] * counts[e] for e in els]
        from math import gcd

        den = 1
        for p in parts:
            den = den * p.denominator // gcd(den, p.denominator)
        ints = [int(p * den) for p in parts]
        g = 0
        for x in ints:
            g = gcd(g, x)
        ints = [x // g for x in ints]
        steps.append("各元素质量比 = " + " : ".join(f"{fmt_num(AR[e])}×{counts[e]}" for e in els) + " = " + " : ".join(map(str, ints)))
        return KernelSolution(kernel="chemistry.mass_ratio", answer=" : ".join(f"{e}" for e in els) + " = " + " : ".join(map(str, ints)),
                              steps=steps, hint="元素质量比 = (相对原子质量 × 原子个数) 之比，最后化成最简整数比。",
                              explanation="化合物中各元素的质量比。", answer_value=", ".join(map(str, ints)), answer_kind="nums",
                              check="比例还原", confidence=0.9)
    el = _element_in(s)
    if el is None or el not in counts:
        return None
    part = AR[el] * counts[el]
    frac = part / mr
    steps.append(f"{el} 的质量分数 = {fmt_num(AR[el])}×{counts[el]} / {fmt_num(mr)} × 100% = {_pct(frac)}%")
    m_total = re.search(r"(\d+(?:\.\d+)?)\s*(g|克|kg|千克|t|吨)\s*(?:的)?\s*" + re.escape(f), s)
    if m_total and re.search(r"含.{0,6}(?:元素)?(?:的)?质量|中.{0,4}元素的?质量(?:是|为)?多少", s):
        tot = F(m_total.group(1))
        res = tot * frac
        u = m_total.group(2)
        steps.append(f"{el} 元素的质量 = {fmt_num(tot)} {u} × {_pct(frac)}% = {fmt_sig(res)} {u}")
        return KernelSolution(kernel="chemistry.element_mass", answer=f"{fmt_sig(res)} {u}", steps=steps,
                              hint="元素质量 = 化合物质量 × 该元素的质量分数。", explanation="化合物中某元素的质量。",
                              answer_value=fmt_num(res, max_dec=4) if "/" not in fmt_num(res, max_dec=4) else fmt_sig(res),
                              answer_kind="num", unit=u, check="质量分数复算", confidence=0.9)
    return KernelSolution(kernel="chemistry.mass_fraction", answer=f"{_pct(frac)}%", steps=steps,
                          hint="某元素质量分数 = 该元素相对原子质量 × 原子个数 ÷ 相对分子质量 × 100%。",
                          explanation="化合物中元素的质量分数。", answer_value=_pct_val(frac), answer_kind="num", unit="%",
                          check="按定义复算", confidence=0.9)


_MASS = r"(\d+(?:\.\d+)?)\s*(g|克|kg|千克|t|吨)"


def _solve_solution(s: str) -> Optional[KernelSolution]:
    if not re.search(r"溶液|溶质|溶剂|稀释|配制|溶解度", s):
        return None
    if re.search(r"→|=|反应|生成", s):
        return None
    hint = "溶质质量分数 = 溶质质量 ÷ 溶液质量 × 100%；稀释前后溶质质量不变。"
    steps: list[str] = []
    # 饱和溶液：溶解度 S g → S/(100+S)
    msol = re.search(r"溶解度(?:为|是)\s*(\d+(?:\.\d+)?)\s*(?:g|克)", s)
    if msol and re.search(r"饱和", s) and re.search(r"质量分数", s):
        S = F(msol.group(1))
        w = S / (100 + S)
        steps.append(f"饱和溶液中，100 g 水最多溶解 {fmt_num(S)} g 溶质，溶液质量 = 100 + {fmt_num(S)} = {fmt_num(100 + S)} g")
        steps.append(f"溶质质量分数 = {fmt_num(S)} ÷ {fmt_num(100 + S)} × 100% ≈ {fmt_sig(w * 100)}%")
        val = f"{float(w * 100):.1f}" if re.search(r"一位小数", s) else _pct_val(w)
        return KernelSolution(kernel="chemistry.solution", answer=f"{val}%", steps=steps, hint="饱和溶液的溶质质量分数 = S ÷ (100 + S) × 100%（S 是溶解度）。",
                              explanation="溶解度与溶质质量分数。", answer_value=val, answer_kind="num", unit="%", check="按定义复算", confidence=0.85)
    # 已知溶液质量与质量分数，求溶质
    mss = re.search(rf"{_MASS}\s*(?:溶质)?质量分数为\s*(\d+(?:\.\d+)?)\s*%\s*的.{{0,8}}?溶液", s)
    if mss and re.search(r"含.{0,8}?(?:多少|几)|溶质.{0,6}(?:多少|几)", s) and not re.search(r"稀释|加水|配制", s):
        a, u, p = F(mss.group(1)), mss.group(2), F(mss.group(3)) / 100
        v = a * p
        steps.append(f"溶质质量 = 溶液质量 × 溶质质量分数 = {fmt_num(a)} {u} × {_pct(p)}% = {fmt_num(v)} {u}")
        return KernelSolution(kernel="chemistry.solution", answer=f"{fmt_num(v)} {u}", steps=steps, hint=hint, explanation="溶质质量的计算。",
                              answer_value=fmt_num(v, max_dec=4), answer_kind="num", unit=u, check="溶质/溶液复算", confidence=0.85)
    # 稀释：把 a g 质量分数为 p% 的溶液稀释成 q%，需加水多少
    m = re.search(rf"{_MASS}\s*(?:溶质)?(?:质量分数为|浓度为|的)?\s*(\d+(?:\.\d+)?)\s*%", s) or re.search(
        rf"(\d+(?:\.\d+)?)\s*%\s*的?.{{0,8}}?溶液\s*{_MASS}", s)
    mq = re.search(r"(?:稀释(?:成|为)|配制成|变为|配成)\s*(?:溶质质量分数为)?\s*(\d+(?:\.\d+)?)\s*%", s)
    if m and mq and re.search(r"加水|水.{0,4}多少|需要水", s):
        if m.lastindex == 3 and m.group(2) in ("g", "克", "kg", "千克", "t", "吨"):
            a, u, p = F(m.group(1)), m.group(2), F(m.group(3)) / 100
        else:
            p, a, u = F(m.group(1)) / 100, F(m.group(2)), m.group(3)
        q = F(mq.group(1)) / 100
        if not 0 < q < p:
            return None
        solute = a * p
        new = solute / q
        w = new - a
        steps += [f"稀释前后溶质质量不变：溶质 = {fmt_num(a)} {u} × {_pct(p)}% = {fmt_num(solute)} {u}",
                  f"稀释后溶液质量 = {fmt_num(solute)} ÷ {_pct(q)}% = {fmt_num(new)} {u}",
                  f"需加水 = {fmt_num(new)} - {fmt_num(a)} = {fmt_num(w)} {u}"]
        return KernelSolution(kernel="chemistry.dilution", answer=f"{fmt_num(w)} {u}", steps=steps, hint=hint, explanation="溶液的稀释。",
                              answer_value=fmt_num(w, max_dec=4), answer_kind="num", unit=u, check="稀释后质量分数复算", confidence=0.85)
    # 配制：配制 a g 质量分数为 p% 的溶液，需溶质/水多少
    m = re.search(rf"配制\s*{_MASS}\s*(?:溶质)?(?:质量分数为|的)?\s*(\d+(?:\.\d+)?)\s*%", s)
    if m:
        a, u, p = F(m.group(1)), m.group(2), F(m.group(3)) / 100
        solute = a * p
        water = a - solute
        steps.append(f"溶质质量 = 溶液质量 × 溶质质量分数 = {fmt_num(a)} × {_pct(p)}% = {fmt_num(solute)} {u}")
        steps.append(f"水的质量 = {fmt_num(a)} - {fmt_num(solute)} = {fmt_num(water)} {u}")
        ask_water = re.search(r"水.{0,6}(?:多少|几)", s) and not re.search(r"(?:氯化钠|溶质|蔗糖|食盐|硝酸钾|氢氧化钠).{0,6}(?:多少|几)", s)
        ask_both = re.search(r"(?:溶质|氯化钠|食盐|蔗糖|硝酸钾|氢氧化钠).{0,10}水.{0,6}(?:多少|各)|各.{0,4}多少", s)
        if ask_both:
            return KernelSolution(kernel="chemistry.solution", answer=f"溶质 {fmt_num(solute)} {u}，水 {fmt_num(water)} {u}", steps=steps,
                                  hint=hint, explanation="配制一定溶质质量分数的溶液。", answer_value=f"{fmt_num(solute, max_dec=4)}, {fmt_num(water, max_dec=4)}",
                                  answer_kind="nums", unit=u, check="溶质+水=溶液", confidence=0.85)
        v = water if ask_water else solute
        return KernelSolution(kernel="chemistry.solution", answer=f"{fmt_num(v)} {u}", steps=steps, hint=hint,
                              explanation="配制一定溶质质量分数的溶液。", answer_value=fmt_num(v, max_dec=4), answer_kind="num", unit=u,
                              check="溶质+水=溶液", confidence=0.85)
    # 求质量分数：a g 溶质溶于 b g 水 / 溶液 b g 中含溶质 a g
    m1 = re.search(rf"(?:把|将|用)?\s*{_MASS}\s*.{{0,8}}?(?:溶于|溶解在|加入到?|放入)\s*{_MASS}\s*(?:的)?水", s)
    m2 = re.search(rf"{_MASS}\s*.{{0,6}}?溶液.{{0,6}}?(?:中)?(?:含有?|溶有)\s*.{{0,6}}?{_MASS}", s)
    if re.search(r"质量分数|浓度", s) and (m1 or m2):
        if m1:
            a, u, b = F(m1.group(1)), m1.group(2), F(m1.group(3))
            total = a + b
            steps.append(f"溶液质量 = 溶质 + 溶剂 = {fmt_num(a)} + {fmt_num(b)} = {fmt_num(total)} {u}")
        else:
            assert m2 is not None
            total, u, a = F(m2.group(1)), m2.group(2), F(m2.group(3))
        if not 0 < a < total:
            return None
        w = a / total
        steps.append(f"溶质质量分数 = {fmt_num(a)} ÷ {fmt_num(total)} × 100% = {_pct(w)}%")
        return KernelSolution(kernel="chemistry.solution", answer=f"{_pct(w)}%", steps=steps, hint=hint, explanation="溶质质量分数。",
                              answer_value=_pct_val(w), answer_kind="num", unit="%", check="溶质/溶液复算", confidence=0.85)
    return None


# ── 根据化学方程式计算 ───────────────────────────────────────────────────────


def _equation(s: str) -> Optional[tuple[list[str], list[str]]]:
    m = re.search(rf"((?:{_FORMULA}\s*\+\s*)*{_FORMULA})\s*(?:=|==|→|->|⟶|═|\s=\s)\s*(?:[^\x00-\x7f]{{0,4}})?\s*((?:{_FORMULA}\s*\+\s*)*{_FORMULA}(?:\s*↑|\s*↓)?)", s)
    if not m:
        return None
    left = [re.sub(r"^\d+", "", x.strip()) for x in m.group(1).split("+")]
    right = [re.sub(r"^\d+", "", x.strip().rstrip("↑↓ ")) for x in m.group(2).split("+")]
    if not left or not right or any(_parse(x) is None for x in left + right):
        return None
    # OCR 丢了下标（CH4→CH、O2→O、H2O→HO）时会配出“看似成立”的错方程：这些写法初中不会出现，直接放弃
    if any(x in _IMPLAUSIBLE for x in left + right):
        return None
    return left, right


_IMPLAUSIBLE = {"O", "H", "N", "Cl", "F", "Br", "I", "CH", "HO", "CH2", "CH3", "NH", "NH2", "SO", "C2"}


def _balance(left: list[str], right: list[str]) -> Optional[list[int]]:
    try:
        from oprim.chemical_equation import balance_coefficients, composition_matrix, parse_formula

        sp_ = [parse_formula(x) for x in left + right]
        return list(balance_coefficients(composition_matrix(sp_, n_reactants=len(left))))
    except Exception:  # noqa: BLE001
        return None


def _species_for(s: str, start: int, species: list[str]) -> Optional[str]:
    """质量数值后面（或前面）紧跟的物质：化学式或常见中文名。"""
    after = s[start:start + 14]
    for f in sorted(species, key=len, reverse=True):
        if re.match(rf"\s*(?:的)?\s*{re.escape(f)}(?![a-z0-9])", after):
            return f
    for name, f in sorted(_NAMES.items(), key=lambda kv: -len(kv[0])):
        if f in species and re.match(rf"\s*(?:的)?\s*{name}", after):
            return f
    return None


def _solve_stoich(s: str) -> Optional[KernelSolution]:
    s = _strip_given(s)
    eq = _equation(s)
    if eq is None:
        return None
    left, right = eq
    species = left + right
    coefs = _balance(left, right)
    if coefs is None:
        return None
    masses = list(re.finditer(_MASS, s))
    if len(masses) != 1:
        return None
    if re.search(r"配平", s):
        return None
    mm = masses[0]
    known = _species_for(s, mm.end(), species)
    if known is None:
        # “生成 4.4g 二氧化碳”这种写法质量在前；“二氧化碳 4.4 g”在后
        before = s[max(0, mm.start() - 12):mm.start()]
        for name, f in _NAMES.items():
            if f in species and name in before:
                known = f
        for f in species:
            if f in before:
                known = f
    if known is None:
        return None
    q = s[mm.end():]
    target = None
    m_t = re.search(r"(?:生成|得到|制得|产生|需要|消耗|参加反应的|理论上可|可制得|可得到|至少需要)\s*(?:的)?\s*([^\s,，。?？多少]{1,8}?)(?:的质量)?(?:是|为)?\s*(?:多少|几)", q) or re.search(
        r"(?:求|则)\s*(?:生成|需要|消耗|参加反应的|得到)?\s*(?:的)?\s*([^\s,，。?？]{1,8}?)的质量", q)
    if m_t:
        word = m_t.group(1)
        for f in sorted(species, key=len, reverse=True):
            if f in word:
                target = f
                break
        if target is None:
            for name, f in sorted(_NAMES.items(), key=lambda kv: -len(kv[0])):
                if name in word and f in species:
                    target = f
                    break
    if target is None or target == known:
        return None
    mr = {f: _mr(_parse(f) or {}) for f in species}
    if any(v is None for v in mr.values()):
        return None
    ck, ct = coefs[species.index(known)], coefs[species.index(target)]
    mk, mt = ck * mr[known], ct * mr[target]  # type: ignore[operator]
    given = F(mm.group(1))
    unit = mm.group(2)
    purity = re.search(r"含\s*[\u4e00-\u9fffA-Za-z0-9]{0,8}?\s*(\d+(?:\.\d+)?)\s*%", s)
    pure_note = ""
    if purity:
        pv = F(purity.group(1)) / 100
        if not 0 < pv <= 1:
            return None
        pure_note = f"纯净物质量 = {fmt_num(given)} {unit} × {fmt_num(pv * 100)}% = {fmt_num(given * pv)} {unit}"
        given = given * pv
    res = given * mt / mk
    eq_txt = " + ".join(f"{c if c > 1 else ''}{f}" for c, f in zip(coefs[:len(left)], left)) + " = " + " + ".join(
        f"{c if c > 1 else ''}{f}" for c, f in zip(coefs[len(left):], right))
    steps = ([pure_note] if pure_note else []) + [f"设生成（或需要）{target} 的质量为 x",
             f"配平的化学方程式：{eq_txt}",
             f"相关物质的质量关系：{ck if ck > 1 else ''}{known} ~ {ct if ct > 1 else ''}{target}，{fmt_num(ck)}×{fmt_num(mr[known])} = {fmt_num(mk)}，{fmt_num(ct)}×{fmt_num(mr[target])} = {fmt_num(mt)}",  # type: ignore[arg-type]
             f"列比例式：{fmt_num(mk)} / {fmt_num(mt)} = {fmt_num(given)} {unit} / x",
             f"x = {fmt_num(given)} × {fmt_num(mt)} ÷ {fmt_num(mk)} = {fmt_sig(res)} {unit}",
             f"答：{target} 的质量为 {fmt_sig(res)} {unit}"]
    # 复核：配平守恒 + 比例
    if res * mk != given * mt:
        return None
    return KernelSolution(kernel="chemistry.stoichiometry", answer=f"{fmt_sig(res)} {unit}", steps=steps,
                          hint="先写出并配平化学方程式，找出已知物质和所求物质的“系数×相对分子质量”，列比例式求解。",
                          explanation="根据化学方程式的计算（质量守恒、按比例）。",
                          answer_value=fmt_num(res, max_dec=4) if "/" not in fmt_num(res, max_dec=4) else fmt_sig(res),
                          answer_kind="num", unit=unit, check="配平原子守恒 + 比例复算", confidence=0.85)


def solve_balance(text: str) -> Optional[KernelSolution]:
    """化学方程式配平（同步）：守恒矩阵零空间 → 最小正整数系数，逐元素复核原子数。"""
    s = _norm(text)
    if not re.search(r"配平|化学计量数|系数", s):
        return None
    s = _strip_given(s)
    eq = _equation(s)
    if eq is None:
        return None
    left, right = eq
    coefs = _balance(left, right)
    if coefs is None:
        return None
    species = left + right
    counts = [_parse(f) or {} for f in species]
    els = sorted({e for c in counts for e in c})
    steps = ["配平依据：化学反应前后每种原子的个数相等"]
    for e in els:
        lsum = sum(coefs[i] * counts[i].get(e, 0) for i in range(len(left)))
        rsum = sum(coefs[i] * counts[i].get(e, 0) for i in range(len(left), len(species)))
        if lsum != rsum:
            return None
        steps.append(f"{e}：左边 {lsum} 个，右边 {rsum} 个 ✓")
    eq_txt = " + ".join(f"{c if c > 1 else ''}{f}" for c, f in zip(coefs[:len(left)], left)) + " = " + " + ".join(
        f"{c if c > 1 else ''}{f}" for c, f in zip(coefs[len(left):], right))
    steps.insert(1, f"配平结果：{eq_txt}")
    return KernelSolution(kernel="chemistry.balance", answer=eq_txt, steps=steps,
                          hint="从只出现在一种反应物和一种生成物里、原子数最多的元素入手（最小公倍数法/奇数配偶法），最后检查每种原子个数。",
                          explanation="化学方程式配平（原子守恒），系数取最小正整数。", answer_value=", ".join(str(c) for c in coefs),
                          answer_kind="nums", check="逐元素原子守恒", confidence=0.95)


__all__ = ["AR", "solve_balance", "solve_chemistry_calc"]
