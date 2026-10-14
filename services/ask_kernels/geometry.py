"""几何数值内核：勾股定理、直角三角形边角（特殊角/已知三角函数值）、三角形/四边形/圆/扇形的面积周长与弧长、
多边形内角和外角、三角形内角、相似三角形的比。

只处理题面里能明确识别出“哪个量是什么”的情形；角色不明确（比如等腰三角形 50° 是顶角还是底角）不作答。
"""

from __future__ import annotations

import re
from typing import Any, Optional

from services.ask_kernels.core import KernelSolution, basic_normalize, cn_small_number
from services.ask_kernels.sym import fmt, value_str

_N = r"(\d+(?:\.\d+)?)"
_UNIT = r"\s*(cm|mm|dm|km|m|厘米|毫米|分米|千米|米)?"


def _R(s: str) -> Any:
    import sympy as sp

    return sp.Rational(s)


def _unit(raw: str) -> str:
    m = re.search(r"\d\s*(cm|mm|dm|km|m|厘米|毫米|分米|千米|米)(?![a-z²³^])", raw)
    if not m:
        return ""
    return {"厘米": "cm", "毫米": "mm", "分米": "dm", "千米": "km", "米": "m"}.get(m.group(1), m.group(1))


def _pi_mode(raw: str) -> Optional[Any]:
    import sympy as sp

    m = re.search(r"(?:π|pi)\s*(?:取|≈|约等于|按)\s*(3\.14\d*)", raw)
    if m:
        return sp.Rational(m.group(1))
    return None


def _with_unit(v: Any, unit: str, power: int = 1) -> str:
    if not unit:
        return fmt(v)
    return f"{fmt(v)} {unit}{'' if power == 1 else ('²' if power == 2 else '³')}"


def _sol(kernel: str, answer: str, steps: list[str], hint: str, expl: str, val: Any, kind: str = "num", unit: str = "", check: str = "") -> KernelSolution:
    return KernelSolution(
        kernel=kernel, answer=answer, steps=steps, hint=hint, explanation=expl,
        answer_value=val if isinstance(val, str) else value_str(val), answer_kind=kind, unit=unit, check=check or "逆运算复核",
    )


# ── 勾股定理 / 直角三角形 ────────────────────────────────────────────────────


def solve_pythagoras(text: str) -> Optional[KernelSolution]:
    import sympy as sp

    raw = basic_normalize(text)
    if not re.search(r"直角三角形|Rt\s*△|Rt三角形|勾股|∠\s*[A-Z]\s*=\s*90", raw):
        return None
    if re.search(r"sin|cos|tan|∠\s*[A-Z]\s*=\s*(30|45|60)\s*°", raw):
        return None
    unit = _unit(raw)
    legs = re.search(rf"两(?:条)?直角边(?:的长)?(?:分别)?(?:为|是|长为|长)\s*{_N}{_UNIT}\s*(?:和|,|、|与)\s*{_N}", raw)
    iso = re.search(rf"等腰直角三角形.{{0,10}}?直角边(?:的)?(?:长)?(?:为|是|等于)?\s*{_N}", raw)
    iso_h = re.search(rf"等腰直角三角形.{{0,10}}?斜边(?:的)?(?:长)?(?:为|是|等于)?\s*{_N}", raw)
    if iso and not legs:
        legs = None
        a0 = _R(iso.group(1))
        steps0 = [f"等腰直角三角形两条直角边相等，都是 {fmt(a0)}"]
        c0 = sp.sqrt(2) * a0
        if re.search(r"面积", raw):
            area = a0 * a0 / 2
            return _sol("geometry.pythagoras", fmt(area), steps0 + [f"面积 = ½ × {fmt(a0)} × {fmt(a0)} = {fmt(area)}"],
                        "等腰直角三角形：两直角边相等，斜边 = √2 × 直角边。", "勾股定理。", area)
        steps0.append(f"斜边² = {fmt(a0)}² + {fmt(a0)}² = {fmt(2 * a0 * a0)}，斜边 = {fmt(c0)}")
        return _sol("geometry.pythagoras", f"{fmt(c0)}（≈ {float(c0):.3g}）", steps0,
                    "等腰直角三角形：两直角边相等，斜边 = √2 × 直角边。", "勾股定理。", c0, unit=_unit(raw), check="a²+a²=c²")
    if iso_h and not legs:
        c0 = _R(iso_h.group(1))
        a0 = sp.radsimp(c0 / sp.sqrt(2))
        steps0 = ["等腰直角三角形两条直角边相等，设为 a", f"a² + a² = {fmt(c0)}²，a = {fmt(a0)}"]
        return _sol("geometry.pythagoras", fmt(a0), steps0, "等腰直角三角形：斜边 = √2 × 直角边。", "勾股定理。", a0, unit=_unit(raw))
    hyp = re.search(rf"斜边(?:长)?(?:为|是|等于|长)\s*{_N}", raw)
    leg1 = re.search(rf"(?:一条|一)直角边(?:长)?(?:为|是|等于|长)\s*{_N}", raw)
    a = b = c = None
    if legs:
        a, b = _R(legs.group(1)), _R(legs.group(3))
    elif hyp and leg1:
        c, a = _R(hyp.group(1)), _R(leg1.group(1))
    else:
        # Rt△ABC，∠C=90°，AC=3，BC=4
        m90 = re.search(r"∠\s*([A-Z])\s*=\s*90", raw)
        sides = dict((k, _R(v)) for k, v in re.findall(rf"([A-Z]{{2}})\s*=\s*{_N}", raw))
        if not m90 or len(sides) != 2:
            return None
        rv = m90.group(1)
        hyp_name = [s for s in _three_sides(raw) if rv not in s]
        if not hyp_name:
            return None
        hn = hyp_name[0]
        known = {"".join(sorted(k)): v for k, v in sides.items()}
        hk = "".join(sorted(hn))
        if hk in known:
            c = known.pop(hk)
            a = list(known.values())[0]
        else:
            a, b = list(known.values())
    steps: list[str] = []
    ask_height = bool(re.search(r"斜边上的高", raw))
    if c is None:
        assert a is not None and b is not None
        c = sp.sqrt(a**2 + b**2)
        steps.append(f"由勾股定理：斜边² = {fmt(a)}² + {fmt(b)}² = {fmt(a**2 + b**2)}")
        steps.append(f"斜边 = √{fmt(a**2 + b**2)} = {fmt(c)}")
        res, what = c, "斜边"
        if sp.simplify(c**2 - a**2 - b**2) != 0:
            return None
    else:
        assert a is not None
        if c <= a:
            return None
        b = sp.sqrt(c**2 - a**2)
        steps.append(f"由勾股定理：另一条直角边² = {fmt(c)}² - {fmt(a)}² = {fmt(c**2 - a**2)}")
        steps.append(f"另一条直角边 = {fmt(b)}")
        res, what = b, "另一条直角边"
    if ask_height:
        h = sp.radsimp(a * b / c)
        steps.append(f"斜边上的高 = 两直角边之积 ÷ 斜边 = {fmt(a)}×{fmt(b)}÷{fmt(c)} = {fmt(h)}")
        res, what = h, "斜边上的高"
    elif re.search(r"面积", raw) and not re.search(r"斜边.*求|求.*斜边|另一", raw):
        area = a * b / 2
        steps.append(f"面积 = ½ × {fmt(a)} × {fmt(b)} = {fmt(area)}")
        return _sol("geometry.pythagoras", _with_unit(area, unit, 2), steps,
                    "直角三角形：a² + b² = c²（c 是斜边）；面积 = 两直角边乘积的一半。", "勾股定理。", area, unit=f"{unit}²" if unit else "")
    approx = "" if res.is_Rational else f"（≈ {float(res):.3g}）"
    steps.append(f"答：{what}为 {_with_unit(res, unit)}{approx}")
    return _sol("geometry.pythagoras", _with_unit(res, unit) + approx, steps,
                "直角三角形两直角边的平方和等于斜边的平方：a² + b² = c²。先分清哪条是斜边（直角所对的边）。",
                "勾股定理。", res, unit=unit, check="三边满足 a²+b²=c²")


def _three_sides(raw: str) -> list[str]:
    m = re.search(r"△\s*([A-Z])([A-Z])([A-Z])", raw)
    if not m:
        return []
    A, B, C = m.groups()
    return [A + B, B + C, A + C]


_SIN = {30: ("1/2", "√3/2", "√3/3"), 45: ("√2/2", "√2/2", "1"), 60: ("√3/2", "1/2", "√3")}


def solve_right_triangle_trig(text: str) -> Optional[KernelSolution]:
    """Rt△ABC 中 ∠C=90°，已知一个锐角（特殊角或三角函数值）和一条边，求另一条边。"""
    import sympy as sp

    raw = basic_normalize(text)
    m90 = re.search(r"∠\s*([A-Z])\s*=\s*90\s*°?", raw)
    tri = _three_sides(raw)
    if not m90 or not tri:
        return None
    rv = m90.group(1)
    letters = set("".join(tri))
    ang = re.search(r"∠\s*([A-Z])\s*=\s*(\d+)\s*°", raw[: m90.start()] + raw[m90.end():])
    fn = re.search(r"(sin|cos|tan)\s*∠?\s*([A-Z])\s*=\s*(\d+(?:\.\d+)?(?:/\d+)?|√\d+/\d+)", raw)
    if ang and ang.group(1) != rv and int(ang.group(2)) in _SIN:
        A = ang.group(1)
        theta = sp.pi * int(ang.group(2)) / 180
        s_, c_, t_ = sp.sin(theta), sp.cos(theta), sp.tan(theta)
        given_desc = f"∠{A} = {ang.group(2)}°"
    elif fn and fn.group(2) != rv:
        A = fn.group(2)
        vs = fn.group(3)
        if "√" in vs:
            num, den = vs.replace("√", "").split("/")
            v = sp.sqrt(int(num)) / int(den)
        else:
            v = sp.Rational(vs)
        if fn.group(1) == "sin":
            s_ = v
            c_ = sp.sqrt(1 - v**2)
        elif fn.group(1) == "cos":
            c_ = v
            s_ = sp.sqrt(1 - v**2)
        else:
            t_v = v
            c_ = 1 / sp.sqrt(1 + t_v**2)
            s_ = t_v * c_
        if not (0 < s_ < 1 and 0 < c_ < 1):
            return None
        t_ = s_ / c_
        given_desc = f"{fn.group(1)}{A} = {fmt(v)}"
    else:
        return None
    if A not in letters or rv not in letters:
        return None
    B = (letters - {A, rv}).pop()
    opp, adj, hyp = "".join(sorted(B + rv)), "".join(sorted(A + rv)), "".join(sorted(A + B))
    sides = {"".join(sorted(k)): _R(v) for k, v in re.findall(rf"([A-Z]{{2}})\s*=\s*{_N}", raw)}
    if len(sides) != 1:
        return None
    (gk, gv), = sides.items()
    want = re.search(r"求\s*([A-Z]{2})|([A-Z]{2})\s*(?:的长|=\s*\?|等于多少|是多少)", raw)
    if not want:
        return None
    wk = "".join(sorted(want.group(1) or want.group(2)))
    if wk == gk:
        return None
    ratio = {opp: s_, adj: c_, hyp: sp.Integer(1)}
    if gk not in ratio or wk not in ratio:
        return None
    res = sp.radsimp(gv * ratio[wk] / ratio[gk])
    steps = [f"在 Rt△ 中 ∠{rv} = 90°，{given_desc}",
             f"∠{A} 的对边是 {opp}，邻边是 {adj}，斜边是 {hyp}",
             f"sin{A} = {opp}/{hyp} = {fmt(s_)}，cos{A} = {adj}/{hyp} = {fmt(c_)}，tan{A} = {opp}/{adj} = {fmt(sp.radsimp(t_))}"]
    rel = f"{wk} = {gk} × {fmt(sp.radsimp(ratio[wk] / ratio[gk]))} = {fmt(gv)} × {fmt(sp.radsimp(ratio[wk] / ratio[gk]))} = {fmt(res)}"
    steps.append(rel)
    unit = _unit(raw)
    approx = "" if res.is_Rational else f"（≈ {float(res):.3g}）"
    # 校验：勾股
    hv = gv / ratio[gk]
    if sp.simplify((hv * s_) ** 2 + (hv * c_) ** 2 - hv**2) != 0:
        return None
    return _sol("geometry.right_triangle_trig", f"{wk} = {_with_unit(res, unit)}{approx}", steps,
                "先找准角的对边、邻边和斜边：sin = 对边/斜边，cos = 邻边/斜边，tan = 对边/邻边。",
                "解直角三角形（锐角三角函数）。", res, unit=unit, check="三边满足勾股定理")


# ── 圆、扇形 ─────────────────────────────────────────────────────────────────


def solve_circle(text: str) -> Optional[KernelSolution]:
    import sympy as sp

    raw = basic_normalize(text)
    if not re.search(r"圆|扇形|弧", raw) or re.search(r"圆柱|圆锥|球", raw):
        return None
    unit = _unit(raw)
    r = None
    mr = re.search(rf"半径(?:为|是|长为|等于|长)?\s*{_N}", raw)
    md = re.search(rf"直径(?:为|是|长为|等于|长)?\s*{_N}", raw)
    if mr:
        r = _R(mr.group(1))
    elif md:
        r = _R(md.group(1)) / 2
    ma = re.search(r"圆心角(?:为|是|等于)?\s*(\d+(?:\.\d+)?)\s*°", raw)
    pi_v = _pi_mode(raw)
    PI = pi_v if pi_v is not None else sp.pi
    steps: list[str] = []
    if r is None:
        mc = re.search(rf"周长(?:为|是|等于)\s*{_N}\s*(?:π|pi)?", raw)
        if mc and re.search(r"面积", raw):
            C = _R(mc.group(1)) * (sp.pi if re.search(rf"周长(?:为|是|等于)\s*{_N}\s*(?:π|pi)", raw) else 1)
            r = C / (2 * PI)
            steps.append(f"由周长 C = 2πr 得 r = {fmt(C)} ÷ (2π) = {fmt(r)}")
        else:
            return None
    else:
        if md and not mr:
            steps.append(f"半径 r = 直径 ÷ 2 = {fmt(r)}")
    semi = bool(re.search(r"半圆", raw))
    if semi and not ma:
        if re.search(r"面积", raw):
            res = PI * r**2 / 2
            steps.append(f"半圆面积 = πr²/2 = π×{fmt(r)}²/2 = {fmt(res)}")
            power, what = 2, "面积"
        elif re.search(r"周长", raw):
            res = PI * r + 2 * r
            steps.append(f"半圆周长 = 半个圆周 + 直径 = πr + 2r = {fmt(PI * r)} + {fmt(2 * r)} = {fmt(res)}")
            power, what = 1, "周长"
        else:
            return None
        u = f"{unit}{'²' if power == 2 else ''}" if unit else ""
        return _sol("geometry.circle", f"{what} = {fmt(res)}{(' ' + u) if u else ''}", steps,
                    "半圆的周长 = 圆周长的一半 + 直径（别漏了直径）；面积 = 圆面积的一半。", "圆的有关计算。", res, unit=u)
    if ma:
        n = _R(ma.group(1))
        if re.search(r"弧长", raw):
            res = n * PI * r / 180
            steps.append(f"弧长 l = nπr/180 = {fmt(n)}×π×{fmt(r)}/180 = {fmt(res)}")
            power, what = 1, "弧长"
        elif re.search(r"面积", raw):
            res = n * PI * r**2 / 360
            steps.append(f"扇形面积 S = nπr²/360 = {fmt(n)}×π×{fmt(r)}²/360 = {fmt(res)}")
            power, what = 2, "扇形面积"
        elif re.search(r"周长", raw):
            arc = n * PI * r / 180
            res = arc + 2 * r
            steps.append(f"弧长 = nπr/180 = {fmt(arc)}，扇形周长 = 弧长 + 2r = {fmt(res)}")
            power, what = 1, "扇形周长"
        else:
            return None
        hint = "弧长 l = nπr/180，扇形面积 S = nπr²/360 = ½lr。"
        kernel = "geometry.sector"
    else:
        asks_area = re.search(r"面积", raw)
        asks_c = re.search(r"周长", raw)
        if asks_area and (not asks_c or asks_area.start() > (asks_c.start() if not steps else -1)):
            res = PI * r**2
            steps.append(f"圆的面积 S = πr² = π×{fmt(r)}² = {fmt(res)}")
            power, what = 2, "面积"
        elif asks_c:
            res = 2 * PI * r
            steps.append(f"圆的周长 C = 2πr = 2×π×{fmt(r)} = {fmt(res)}")
            power, what = 1, "周长"
        else:
            return None
        hint = "圆的周长 C = 2πr = πd，面积 S = πr²；先确认给的是半径还是直径。"
        kernel = "geometry.circle"
    res = sp.nsimplify(res) if pi_v is not None else res
    approx = f"（≈ {float(res):.4g}）" if pi_v is None else ""
    if pi_v is not None:
        steps.append(f"π 取 {fmt(pi_v)}")
    u = f"{unit}{'²' if power == 2 else ''}" if unit else ""
    return _sol(kernel, f"{what} = {fmt(res)}{(' ' + u) if u else ''}{approx}", steps, hint, "圆与扇形的有关计算。", res, unit=u, check="公式反推半径一致")


# ── 平面图形面积周长 ─────────────────────────────────────────────────────────


def solve_plane_figure(text: str) -> Optional[KernelSolution]:
    import sympy as sp

    raw = basic_normalize(text)
    unit = _unit(raw)
    steps: list[str] = []
    want_area = bool(re.search(r"面积", raw))
    want_per = bool(re.search(r"周长", raw))
    if want_area == want_per:
        return None
    if re.search(r"梯形", raw):
        m = re.search(rf"上底(?:为|是|长)?\s*{_N}.*?下底(?:为|是|长)?\s*{_N}.*?高(?:为|是)?\s*{_N}", raw)
        if not (m and want_area):
            return None
        a, b, h = (_R(m.group(i)) for i in (1, 2, 3))
        res = (a + b) * h / 2
        steps.append(f"梯形面积 = (上底 + 下底) × 高 ÷ 2 = ({fmt(a)} + {fmt(b)}) × {fmt(h)} ÷ 2 = {fmt(res)}")
        kernel = "geometry.trapezoid"
    elif re.search(r"平行四边形", raw):
        m = re.search(rf"底(?:边)?(?:长)?(?:为|是)?\s*{_N}.*?高(?:为|是)?\s*{_N}", raw)
        if not (m and want_area):
            return None
        a, h = _R(m.group(1)), _R(m.group(2))
        res = a * h
        steps.append(f"平行四边形面积 = 底 × 高 = {fmt(a)} × {fmt(h)} = {fmt(res)}")
        kernel = "geometry.parallelogram"
    elif re.search(r"长方形|矩形", raw):
        m = re.search(rf"长(?:为|是)?\s*{_N}.*?宽(?:为|是)?\s*{_N}", raw)
        if not m:
            return None
        a, b = _R(m.group(1)), _R(m.group(2))
        res = a * b if want_area else 2 * (a + b)
        steps.append(f"{'面积 = 长 × 宽' if want_area else '周长 = (长 + 宽) × 2'} = {fmt(res)}")
        kernel = "geometry.rectangle"
    elif re.search(r"正方形", raw):
        m = re.search(rf"边长(?:为|是)?\s*{_N}", raw)
        if not m:
            return None
        a = _R(m.group(1))
        res = a * a if want_area else 4 * a
        steps.append(f"{'面积 = 边长²' if want_area else '周长 = 4 × 边长'} = {fmt(res)}")
        kernel = "geometry.square"
    elif re.search(r"等边三角形|正三角形", raw):
        m = re.search(rf"边长(?:为|是)?\s*{_N}", raw)
        if not m:
            return None
        a = _R(m.group(1))
        res = sp.sqrt(3) / 4 * a**2 if want_area else 3 * a
        steps.append(("等边三角形面积 = (√3/4)a²" if want_area else "周长 = 3a") + f" = {fmt(res)}")
        kernel = "geometry.equilateral"
    elif re.search(r"三角形", raw) and want_area:
        m = re.search(rf"底(?:边)?(?:长)?(?:为|是)?\s*{_N}.*?(?:这条边上的|边上的|对应的)?高(?:为|是)?\s*{_N}", raw)
        if not m:
            return None
        a, h = _R(m.group(1)), _R(m.group(2))
        res = a * h / 2
        steps.append(f"三角形面积 = 底 × 高 ÷ 2 = {fmt(a)} × {fmt(h)} ÷ 2 = {fmt(res)}")
        kernel = "geometry.triangle_area"
    else:
        return None
    power = 2 if want_area else 1
    u = f"{unit}{'²' if power == 2 else ''}" if unit else ""
    return _sol(kernel, f"{'面积' if want_area else '周长'} = {fmt(res)}{(' ' + u) if u else ''}", steps,
                "先认清图形，再套对应的面积/周长公式，注意单位统一。", "平面图形的面积与周长。", res, unit=u)


# ── 多边形 / 三角形内角 ──────────────────────────────────────────────────────


def _n_sides(raw: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*边形", raw)
    if m:
        return int(m.group(1))
    m = re.search(r"([一二三四五六七八九十两]{1,3})\s*边形", raw)
    if m:
        return cn_small_number(m.group(1))
    return None


def solve_polygon_angles(text: str) -> Optional[KernelSolution]:
    import sympy as sp

    raw = basic_normalize(text)
    if not re.search(r"边形|多边形", raw):
        return None
    hint = "n 边形内角和 = (n-2)×180°，外角和恒为 360°；正 n 边形每个外角 = 360°/n。"
    expl = "多边形的内角和与外角和。"
    n = _n_sides(raw)
    m_sum = re.search(r"内角和(?:是|为|等于)\s*(\d+)\s*°", raw)
    m_ext = re.search(r"每(?:一)?个外角(?:都)?(?:是|为|等于)\s*(\d+(?:\.\d+)?)\s*°", raw)
    m_int = re.search(r"每(?:一)?个内角(?:都)?(?:是|为|等于)\s*(\d+(?:\.\d+)?)\s*°", raw)
    m_ratio = re.search(r"内角和是外角和的\s*(\d+(?:\.\d+)?)\s*倍", raw)
    steps: list[str] = []
    if m_sum and re.search(r"边数|几边形|多少条边|边形的边", raw):
        S = int(m_sum.group(1))
        if S % 180:
            return None
        nv = S // 180 + 2
        steps.append(f"(n - 2) × 180° = {S}°，n - 2 = {S // 180}，n = {nv}")
        return _sol("geometry.polygon", f"{nv} 边形（边数为 {nv}）", steps, hint, expl, sp.Integer(nv))
    if m_ratio:
        k = _R(m_ratio.group(1))
        nv = k * 2 + 2
        if not nv.is_Integer:
            return None
        steps.append(f"(n - 2) × 180° = {fmt(k)} × 360°，n = {fmt(nv)}")
        return _sol("geometry.polygon", f"{fmt(nv)} 边形", steps, hint, expl, nv)
    if m_ext:
        A = _R(m_ext.group(1))
        nv = 360 / A
        if not nv.is_Integer:
            return None
        steps.append(f"多边形外角和为 360°，边数 n = 360° ÷ {fmt(A)}° = {fmt(nv)}")
        if re.search(r"内角和", raw):
            S = (nv - 2) * 180
            steps.append(f"内角和 = (n - 2) × 180° = {fmt(S)}°")
            return _sol("geometry.polygon", f"内角和为 {fmt(S)}°", steps, hint, expl, S, unit="°")
        return _sol("geometry.polygon", f"边数为 {fmt(nv)}", steps, hint, expl, nv)
    if m_int:
        A = _R(m_int.group(1))
        if A >= 180:
            return None
        nv = 360 / (180 - A)
        if not nv.is_Integer:
            return None
        steps.append(f"每个外角 = 180° - {fmt(A)}° = {fmt(180 - A)}°，边数 n = 360° ÷ {fmt(180 - A)}° = {fmt(nv)}")
        return _sol("geometry.polygon", f"边数为 {fmt(nv)}", steps, hint, expl, nv)
    if n is None or n < 3 or n > 100:
        return None
    if re.search(r"外角和", raw):
        steps.append("任意多边形的外角和都是 360°")
        return _sol("geometry.polygon", "外角和为 360°", steps, hint, expl, sp.Integer(360), unit="°")
    if re.search(r"对角线", raw):
        d = n * (n - 3) // 2
        steps.append(f"n 边形的对角线条数 = n(n-3)/2 = {n}×{n - 3}/2 = {d}")
        return _sol("geometry.polygon", f"{d} 条", steps, "从一个顶点出发可以引 (n-3) 条对角线，共 n(n-3)/2 条。", expl, sp.Integer(d))
    regular = bool(re.search(r"正\s*(?:\d+|[一二三四五六七八九十]+)\s*边形", raw))
    if regular and re.search(r"每(?:一)?个内角|内角(?:的度数|是多少|为多少|等于多少)", raw) and not re.search(r"内角和", raw):
        a = sp.Rational((n - 2) * 180, n)
        steps.append(f"正 {n} 边形内角和 = ({n} - 2)×180° = {(n - 2) * 180}°，每个内角 = {(n - 2) * 180}° ÷ {n} = {fmt(a)}°")
        return _sol("geometry.polygon", f"每个内角为 {fmt(a)}°", steps, hint, expl, a, unit="°")
    if regular and re.search(r"每(?:一)?个外角|外角(?:的度数|是多少)", raw):
        a = sp.Rational(360, n)
        steps.append(f"外角和为 360°，正 {n} 边形每个外角 = 360° ÷ {n} = {fmt(a)}°")
        return _sol("geometry.polygon", f"每个外角为 {fmt(a)}°", steps, hint, expl, a, unit="°")
    if re.search(r"内角和", raw):
        S = (n - 2) * 180
        steps.append(f"{n} 边形内角和 = ({n} - 2) × 180° = {S}°")
        return _sol("geometry.polygon", f"内角和为 {S}°", steps, hint, expl, sp.Integer(S), unit="°")
    return None


def solve_triangle_angles(text: str) -> Optional[KernelSolution]:
    import sympy as sp

    raw = basic_normalize(text)
    if not re.search(r"三角形|△", raw) or re.search(r"边形|sin|cos|tan|相似|∽", raw):
        return None
    hint = "三角形内角和为 180°；等腰三角形两底角相等。"
    expl = "三角形内角和定理。"
    steps: list[str] = []
    if re.search(r"等腰", raw):
        mt = re.search(r"顶角(?:的度数)?(?:为|是|等于)\s*(\d+(?:\.\d+)?)\s*°", raw)
        mb = re.search(r"底角(?:的度数)?(?:为|是|等于)\s*(\d+(?:\.\d+)?)\s*°", raw)
        mo = re.search(r"(?:一个|有一个)(?:内)?角(?:为|是|等于)\s*(\d+(?:\.\d+)?)\s*°", raw)
        if mt:
            t = _R(mt.group(1))
            b = (180 - t) / 2
            steps.append(f"底角 = (180° - {fmt(t)}°) ÷ 2 = {fmt(b)}°")
            return _sol("geometry.triangle_angle", f"底角为 {fmt(b)}°", steps, hint, expl, b, unit="°")
        if mb:
            b = _R(mb.group(1))
            if b >= 90:
                return None
            t = 180 - 2 * b
            steps.append(f"顶角 = 180° - 2 × {fmt(b)}° = {fmt(t)}°")
            return _sol("geometry.triangle_angle", f"顶角为 {fmt(t)}°", steps, hint, expl, t, unit="°")
        if mo:
            a = _R(mo.group(1))
            if a >= 90:
                b = (180 - a) / 2
                steps.append(f"{fmt(a)}° ≥ 90°，只能是顶角（底角必须是锐角），底角 = (180° - {fmt(a)}°) ÷ 2 = {fmt(b)}°")
                return _sol("geometry.triangle_angle", f"另外两个角都是 {fmt(b)}°", steps, hint, expl, f"{value_str(b)}, {value_str(b)}", kind="nums", unit="°")
            return None  # 小于 90°：顶角/底角两种情况，分类讨论题不在此作答
        return None
    angs = [_R(a) for a in re.findall(r"(\d+(?:\.\d+)?)\s*°", raw)]
    if len(angs) == 2 and re.search(r"第三个(?:内)?角|另一个(?:内)?角|求\s*∠\s*[A-Z]|∠\s*[A-Z]\s*(?:的度数|=\s*\?|等于多少)", raw):
        c = 180 - sum(angs)
        if c <= 0:
            return None
        steps.append(f"第三个角 = 180° - {fmt(angs[0])}° - {fmt(angs[1])}° = {fmt(c)}°")
        return _sol("geometry.triangle_angle", f"{fmt(c)}°", steps, hint, expl, c, unit="°")
    mr = re.search(r"三个(?:内)?角(?:的度数)?之比(?:为|是)\s*(\d+)\s*:\s*(\d+)\s*:\s*(\d+)", raw)
    if mr:
        k = [int(x) for x in mr.groups()]
        unit_a = sp.Rational(180, sum(k))
        vals = [unit_a * x for x in k]
        steps.append(f"每一份 = 180° ÷ ({'+'.join(map(str, k))}) = {fmt(unit_a)}°，三个角分别为 " + "、".join(f"{fmt(v)}°" for v in vals))
        if re.search(r"最大", raw):
            return _sol("geometry.triangle_angle", f"最大角为 {fmt(max(vals))}°", steps, hint, expl, max(vals), unit="°")
        return _sol("geometry.triangle_angle", "、".join(f"{fmt(v)}°" for v in vals), steps, hint, expl, ", ".join(value_str(v) for v in vals), kind="nums", unit="°")
    return None


# ── 相似三角形 ───────────────────────────────────────────────────────────────


def solve_similar(text: str) -> Optional[KernelSolution]:
    import sympy as sp

    raw = basic_normalize(text)
    if not re.search(r"相似|∽", raw):
        return None
    hint = "相似三角形：对应边的比 = 相似比 = 周长比，面积比 = 相似比的平方。"
    expl = "相似三角形的性质。"
    steps: list[str] = []
    mk = re.search(r"相似比(?:为|是)\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", raw)
    ma = re.search(r"面积(?:之)?比(?:为|是)\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", raw)
    if mk and re.search(r"面积(?:之)?比", raw):
        a, b = _R(mk.group(1)), _R(mk.group(2))
        steps.append(f"面积比 = 相似比² = ({fmt(a)}:{fmt(b)})² = {fmt(a**2)}:{fmt(b**2)}")
        return _sol("geometry.similar", f"{fmt(a**2)}:{fmt(b**2)}", steps, hint, expl, f"{value_str(a**2)}, {value_str(b**2)}", kind="nums")
    if mk and re.search(r"周长(?:之)?比", raw):
        a, b = _R(mk.group(1)), _R(mk.group(2))
        steps.append(f"周长比 = 相似比 = {fmt(a)}:{fmt(b)}")
        return _sol("geometry.similar", f"{fmt(a)}:{fmt(b)}", steps, hint, expl, f"{value_str(a)}, {value_str(b)}", kind="nums")
    m_sa = re.search(rf"(较小|小|较大|大)(?:的)?三角形(?:的)?面积(?:为|是)\s*{_N}", raw)
    if mk and m_sa and re.search(r"求.{0,6}(?:较大|大|较小|小)(?:的)?三角形(?:的)?面积", raw):
        a, b = _R(mk.group(1)), _R(mk.group(2))
        small_first = a < b
        given = _R(m_sa.group(2))
        given_is_small = "小" in m_sa.group(1)
        k2 = (b / a) ** 2 if small_first else (a / b) ** 2
        res = given * k2 if given_is_small else given / k2
        steps.append(f"面积比 = 相似比的平方 = ({fmt(min(a, b))}:{fmt(max(a, b))})² = {fmt(min(a, b) ** 2)}:{fmt(max(a, b) ** 2)}")
        steps.append(f"所求面积 = {fmt(given)} × {fmt(k2 if given_is_small else 1 / k2)} = {fmt(res)}")
        return _sol("geometry.similar", fmt(res), steps, hint, expl, res)
    if ma and re.search(r"相似比|周长(?:之)?比|对应边", raw):
        a, b = _R(ma.group(1)), _R(ma.group(2))
        ra, rb = sp.sqrt(a), sp.sqrt(b)
        g = sp.gcd(ra, rb) if ra.is_Integer and rb.is_Integer else 1
        ra, rb = ra / g, rb / g
        steps.append(f"相似比 = √(面积比) = √{fmt(a)} : √{fmt(b)} = {fmt(ra)}:{fmt(rb)}")
        return _sol("geometry.similar", f"{fmt(ra)}:{fmt(rb)}", steps, hint, expl, f"{value_str(ra)}, {value_str(rb)}", kind="nums")
    m = re.search(r"△\s*([A-Z]{3})\s*∽\s*△\s*([A-Z]{3})", raw)
    if not m:
        return None
    t1, t2 = m.group(1), m.group(2)
    mp = {t1[i]: t2[i] for i in range(3)}
    inv = {t2[i]: t1[i] for i in range(3)}
    sides = {k: _R(v) for k, v in re.findall(rf"(?<![A-Z])([A-Z]{{2}})\s*=\s*{_N}", raw)}
    want = re.search(r"求\s*([A-Z]{2})|([A-Z]{2})\s*(?:的长|=\s*\?|等于多少|是多少)", raw)
    if not want:
        return None
    w = want.group(1) or want.group(2)

    def corr(sname: str) -> Optional[str]:
        if all(c in mp for c in sname) and set(sname) <= set(t1):
            return mp[sname[0]] + mp[sname[1]]
        if all(c in inv for c in sname) and set(sname) <= set(t2):
            return inv[sname[0]] + inv[sname[1]]
        return None

    def get(sname: str) -> Optional[Any]:
        for k, v in sides.items():
            if set(k) == set(sname):
                return v
        return None

    wc = corr(w)
    if wc is None or get(wc) is None:
        return None
    ratio = None
    for k, v in sides.items():
        if set(k) == set(wc):
            continue
        ck = corr(k)
        if ck and get(ck) is not None:
            ratio = (k, v, ck, get(ck))
            break
    if ratio is None:
        return None
    k, v, ck, cv = ratio
    w_tri = t1 if set(w) <= set(t1) else t2
    if not set(k) <= set(w_tri):
        k, v, ck, cv = ck, cv, k, v
    res = get(wc) * v / cv
    steps.append(f"△{t1}∽△{t2}，对应边成比例：{w}/{wc} = {k}/{ck}")
    steps.append(f"{w}/{fmt(get(wc))} = {fmt(v)}/{fmt(cv)}，所以 {w} = {fmt(get(wc))} × {fmt(v)} ÷ {fmt(cv)} = {fmt(res)}")
    unit = _unit(raw)
    return _sol("geometry.similar", f"{w} = {_with_unit(res, unit)}", steps, hint, expl, res, unit=unit, check="对应边比例一致")


__all__ = [
    "solve_circle",
    "solve_plane_figure",
    "solve_polygon_angles",
    "solve_pythagoras",
    "solve_right_triangle_trig",
    "solve_similar",
    "solve_triangle_angles",
]
