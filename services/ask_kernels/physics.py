"""初中物理计算题内核（无 LLM）：已知量抽取（数值 + 单位 → 国际单位）→ 角色识别 → 公式链推导 → 带单位的结果。

覆盖：速度、密度、重力、压强（固体 p=F/S、液体 p=ρgh）、浮力（阿基米德/称重法/漂浮）、杠杆、
功/功率/机械效率（含滑轮组）、热量 Q=cmΔt、燃料 Q=mq（Q=Vq）、热效率、欧姆定律、串并联、
电功率/电能/焦耳热、波速 v=λf 与声/光传播（回声）。

做法：
1. 抽取 “数值 + 单位”（支持 4.2×10³、kW·h、g/cm³、℃ 等），换算成国际单位；
2. 按数值前面的中文语境给它一个角色（路程/深度/动力臂/示数/R1……），同一角色出现两个不同数值 → 不作答；
3. 从问句找出所求量（和题目要求的单位）；
4. 用公式表做前向推导（只用题目条件允许的关系，如“水平面上 F=G”“浸没 V排=V”“漂浮 F浮=G”），
   每一步记 “公式 → 代入 → 结果”；推不出所求量就返回 None；
5. 把结果代回所用公式复核（逆运算），通过才返回。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Callable, Optional

from services.ask_kernels.core import KernelSolution, basic_normalize, fmt_num, fmt_sig

F = Fraction

# 单位 → (量纲, 换算到国际单位的系数, 显示名)
_UNITS: dict[str, tuple[str, Fraction, str]] = {
    "km/h": ("speed", F(5, 18), "km/h"), "千米/时": ("speed", F(5, 18), "km/h"), "千米/小时": ("speed", F(5, 18), "km/h"),
    "m/s": ("speed", F(1), "m/s"), "米/秒": ("speed", F(1), "m/s"), "m/min": ("speed", F(1, 60), "m/min"),
    "g/cm^3": ("density", F(1000), "g/cm³"), "kg/m^3": ("density", F(1), "kg/m³"), "g/mL": ("density", F(1000), "g/mL"),
    "J/(kg*℃)": ("c", F(1), "J/(kg·℃)"), "J/(kg℃)": ("c", F(1), "J/(kg·℃)"), "J/(kg.℃)": ("c", F(1), "J/(kg·℃)"),
    "J/kg": ("q", F(1), "J/kg"), "J/m^3": ("qv", F(1), "J/m³"), "N/kg": ("g", F(1), "N/kg"),
    "kW*h": ("energy", F(3600000), "kW·h"), "kWh": ("energy", F(3600000), "kW·h"), "千瓦时": ("energy", F(3600000), "kW·h"),
    "MJ": ("energy", F(10**6), "MJ"), "kJ": ("energy", F(1000), "kJ"), "J": ("energy", F(1), "J"), "焦": ("energy", F(1), "J"),
    "MW": ("power", F(10**6), "MW"), "kW": ("power", F(1000), "kW"), "W": ("power", F(1), "W"), "瓦": ("power", F(1), "W"),
    "MPa": ("pressure", F(10**6), "MPa"), "kPa": ("pressure", F(1000), "kPa"), "Pa": ("pressure", F(1), "Pa"), "帕": ("pressure", F(1), "Pa"),
    "kN": ("force", F(1000), "kN"), "N": ("force", F(1), "N"), "牛": ("force", F(1), "N"),
    "kV": ("voltage", F(1000), "kV"), "mV": ("voltage", F(1, 1000), "mV"), "V": ("voltage", F(1), "V"), "伏": ("voltage", F(1), "V"),
    "mA": ("current", F(1, 1000), "mA"), "A": ("current", F(1), "A"), "安": ("current", F(1), "A"),
    "kΩ": ("resistance", F(1000), "kΩ"), "MΩ": ("resistance", F(10**6), "MΩ"), "Ω": ("resistance", F(1), "Ω"), "欧": ("resistance", F(1), "Ω"),
    "MHz": ("freq", F(10**6), "MHz"), "kHz": ("freq", F(1000), "kHz"), "Hz": ("freq", F(1), "Hz"),
    "m^3": ("volume", F(1), "m³"), "dm^3": ("volume", F(1, 1000), "dm³"), "cm^3": ("volume", F(1, 10**6), "cm³"),
    "mL": ("volume", F(1, 10**6), "mL"), "ml": ("volume", F(1, 10**6), "mL"), "L": ("volume", F(1, 1000), "L"), "升": ("volume", F(1, 1000), "L"),
    "立方米": ("volume", F(1), "m³"), "立方厘米": ("volume", F(1, 10**6), "cm³"), "毫升": ("volume", F(1, 10**6), "mL"),
    "m^2": ("area", F(1), "m²"), "dm^2": ("area", F(1, 100), "dm²"), "cm^2": ("area", F(1, 10**4), "cm²"), "mm^2": ("area", F(1, 10**6), "mm²"),
    "平方米": ("area", F(1), "m²"), "平方厘米": ("area", F(1, 10**4), "cm²"),
    "km": ("length", F(1000), "km"), "千米": ("length", F(1000), "km"), "公里": ("length", F(1000), "km"), "dm": ("length", F(1, 10), "dm"),
    "cm": ("length", F(1, 100), "cm"), "厘米": ("length", F(1, 100), "cm"), "mm": ("length", F(1, 1000), "mm"), "nm": ("length", F(1, 10**9), "nm"),
    "m": ("length", F(1), "m"), "米": ("length", F(1), "m"),
    "kg": ("mass", F(1), "kg"), "千克": ("mass", F(1), "kg"), "mg": ("mass", F(1, 10**6), "mg"), "g": ("mass", F(1, 1000), "g"),
    "克": ("mass", F(1, 1000), "g"), "t": ("mass", F(1000), "t"), "吨": ("mass", F(1000), "t"),
    "min": ("time", F(60), "min"), "分钟": ("time", F(60), "min"), "h": ("time", F(3600), "h"), "小时": ("time", F(3600), "h"),
    "s": ("time", F(1), "s"), "秒": ("time", F(1), "s"),
    "℃": ("temp", F(1), "℃"), "%": ("percent", F(1, 100), "%"),
}
_UNIT_RE = "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))
_NUM_RE = r"(\d+(?:\.\d+)?)(?:\s*[×x*]\s*10\s*\^\s*\(?\s*(-?\d+)\s*\)?)?"
_TOKEN = re.compile(rf"{_NUM_RE}\s*({_UNIT_RE})(?![a-zA-Z²³])")

# 量 → (名称, 国际单位)
_Q: dict[str, tuple[str, str]] = {
    "s": ("路程", "m"), "t": ("时间", "s"), "v": ("速度", "m/s"), "m": ("质量", "kg"), "V": ("体积", "m³"), "rho": ("密度", "kg/m³"),
    "G": ("重力", "N"), "F": ("力", "N"), "Fp": ("压力", "N"), "S": ("受力面积", "m²"), "p": ("压强", "Pa"), "h": ("深度/高度", "m"),
    "rho_l": ("液体密度", "kg/m³"), "Ff": ("浮力", "N"), "Fs": ("弹簧测力计示数", "N"), "Vp": ("排开液体的体积", "m³"),
    "F1": ("动力", "N"), "F2": ("阻力", "N"), "L1": ("动力臂", "m"), "L2": ("阻力臂", "m"),
    "W": ("功", "J"), "Wu": ("有用功", "J"), "Wt": ("总功", "J"), "P": ("功率", "W"), "eta": ("效率", ""), "n": ("承担物重的绳子段数", ""),
    "sr": ("绳子自由端移动的距离", "m"),
    "Q": ("热量", "J"), "c": ("比热容", "J/(kg·℃)"), "dt": ("升高的温度", "℃"), "T1": ("初温", "℃"), "T2": ("末温", "℃"),
    "mf": ("燃料质量", "kg"), "Vf": ("燃料体积", "m³"), "q": ("热值", "J/kg"), "qv": ("热值", "J/m³"), "Qf": ("燃料完全燃烧放出的热量", "J"),
    "U": ("电压", "V"), "I": ("电流", "A"), "R": ("电阻", "Ω"), "R1": ("R₁", "Ω"), "R2": ("R₂", "Ω"), "U1": ("R₁两端电压", "V"),
    "U2": ("R₂两端电压", "V"), "I1": ("通过R₁的电流", "A"), "I2": ("通过R₂的电流", "A"), "We": ("电能", "J"), "Qj": ("电流产生的热量", "J"),
    "lam": ("波长", "m"), "f": ("频率", "Hz"), "g": ("g", "N/kg"),
}


@dataclass
class _Tok:
    start: int
    end: int
    value: Fraction  # SI
    dim: str
    unit: str
    raw: str


def _tokens(s: str) -> list[_Tok]:
    out = []
    for m in _TOKEN.finditer(s):
        base = F(m.group(1))
        if m.group(2):
            base *= F(10) ** int(m.group(2))
        u = m.group(3)
        dim, fac, disp = _UNITS[u]
        out.append(_Tok(m.start(), m.end(), base * fac, dim, disp, m.group(0)))
    return out


def _ctx(s: str, tok: _Tok, n: int = 12) -> str:
    seg = s[max(0, tok.start - n):tok.start]
    seg = re.split(r"[,;。，；:]|\.(?!\d)", seg)[-1]
    return seg.rstrip()


def _ctx_after(s: str, tok: _Tok, n: int = 6) -> str:
    return re.split(r"[,;。，；]", s[tok.end:tok.end + n])[0]


def _role(s: str, tok: _Tok, flags: dict[str, bool]) -> Optional[str]:
    c = _ctx(s, tok)
    a = _ctx_after(s, tok)
    d = tok.dim
    r1 = re.search(r"R\s*1|R₁", c[-6:])
    r2 = re.search(r"R\s*2|R₂", c[-6:])
    if d == "length":
        if re.search(r"动力臂", c):
            return "L1"
        if re.search(r"阻力臂", c):
            return "L2"
        if re.search(r"波长", c):
            return "lam"
        if re.search(r"绳(?:子)?(?:的)?自由端|拉过|绳端", c):
            return "sr"
        if re.search(r"深|水下|水面下|液面下|距水面|距液面|离水面|高(?:度)?(?:为|是)?$|提(?:升|高)|举高|升高|上升|楼高|高处|高的|竖直|匀速提", c) or re.search(r"深|高", a[:2]):
            return "h"
        return "s"
    if d == "force":
        if re.search(r"动力(?!臂)", c):
            return "F1"
        if re.search(r"阻力(?!臂)", c):
            return "F2"
        if re.search(r"浮力|排开(?:的)?(?:水|液体)(?:的)?重|排开(?:的)?(?:水|液体)受到的重力", c):
            return "Ff"
        if re.search(r"示数|读数|测力计", c) and not re.search(r"空气中", c):
            return "Fs"
        if re.search(r"空气中", c):
            return "G"
        if re.search(r"重(?:力)?(?:为|是|约)?$|重为|物重|物体重|重力|所受重力|的重", c) or re.search(r"^\s*的(?:物体|重物|木块|货物)", a):
            return "G"
        if re.search(r"压力", c):
            return "Fp"
        return "F"
    if d == "mass":
        if flags["fuel"] and re.search(r"燃烧|燃料|酒精|煤|汽油|柴油|天然气|焦炭|木炭|干木柴|氢", c + a):
            return "mf"
        return "m"
    if d == "volume":
        if re.search(r"排开|排水|浸入|浸在|浸没.{0,4}体积", c):
            return "Vp"
        if flags["fuel"] and re.search(r"天然气|煤气|燃气|氢气", c + a):
            return "Vf"
        return "V"
    if d == "density":
        if re.search(r"液体|水的|酒精|煤油|盐水|海水|液", c) and (flags["buoy"] or flags["liq_p"]):
            return "rho_l"
        return "rho"
    if d == "temp":
        if re.search(r"升高了|降低了|升高$|降低$", c):
            return "dt"
        if re.search(r"升高到|加热到|到$|降到|降低到|末温|升至", c):
            return "T2"
        if re.search(r"初温|从$|由$|温度为|室温|常温|是$|为$", c):
            return "T1"
        return None
    if d == "voltage":
        if r1:
            return "U1"
        if r2:
            return "U2"
        return "U"
    if d == "current":
        if r1:
            return "I1"
        if r2:
            return "I2"
        return "I"
    if d == "resistance":
        if r1 or re.search(r"R\s*1\s*=?$", c):
            return "R1"
        if r2 or re.search(r"R\s*2\s*=?$", c):
            return "R2"
        return "R"
    if d == "energy":
        if re.search(r"电能|消耗|电功|耗电", c):
            return "We"
        if re.search(r"有用功", c):
            return "Wu"
        if re.search(r"总功", c):
            return "Wt"
        if re.search(r"热量|吸收|放出|放热|吸热", c):
            return "Q"
        return "W"
    return {"speed": "v", "time": "t", "area": "S", "pressure": "p", "power": "P", "c": "c", "q": "q", "qv": "qv",
            "g": "g", "freq": "f", "percent": "eta"}.get(d)


# ── 所求量 ───────────────────────────────────────────────────────────────────

_TARGETS: list[tuple[str, str]] = [
    (r"机械效率|热效率|效率", "eta"),
    (r"有用功", "Wu"), (r"总功", "Wt"),
    (r"浮力", "Ff"),
    (r"液体的?密度|液体密度", "rho_l"),
    (r"密度", "rho"),
    (r"压强", "p"),
    (r"压力", "Fp"),
    (r"动力臂", "L1"), (r"阻力臂", "L2"), (r"动力", "F1"), (r"阻力", "F2"),
    (r"排开.{0,6}体积|V\s*排", "Vp"),
    (r"比热容", "c"), (r"热值", "q"),
    (r"电流.{0,8}产生.{0,6}热量|焦耳热|电热|产生.{0,4}热量", "Qj"),
    (r"放出.{0,4}热量|放热", "Qf"),
    (r"吸收.{0,6}热量|热量", "Q"),
    (r"升高(?:了)?(?:多少|几)|升高.{0,2}温度|温度升高", "dt"),
    (r"末温|升高到多少|温度变为|加热到多少", "T2"),
    (r"消耗.{0,6}电能|电能|电功|耗电|多少度|千瓦时|kW·h", "We"),
    (r"电功率|功率", "P"),
    (r"做.{0,4}?功(?!率)|功是|功为|多少功", "W"),
    (r"总电阻|等效电阻", "R"), (r"R\s*1\s*的阻值|R₁的阻值", "R1"), (r"R\s*2\s*的阻值|R₂的阻值", "R2"), (r"电阻|阻值", "R"),
    (r"R\s*1\s*两端的?电压|R₁两端", "U1"), (r"R\s*2\s*两端的?电压|R₂两端", "U2"), (r"电源电压|电压", "U"),
    (r"通过\s*R\s*1|R₁的电流", "I1"), (r"通过\s*R\s*2|R₂的电流", "I2"), (r"干路电流|总电流|电流", "I"),
    (r"波长", "lam"), (r"频率", "f"),
    (r"重力|物重|多重|重为多少", "G"),
    (r"质量", "m"),
    (r"体积", "V"),
    (r"速度|多快", "v"),
    (r"路程|距离|多远|多长的路|深度|多深|高度|多高", "s"),
    (r"时间|多久|多长时间|几小时|几秒|多少秒|多少分钟|多少小时", "t"),
]

_ASK_UNIT = re.compile(rf"(?:合|多少|几|是|为|等于)\s*({_UNIT_RE})(?![a-zA-Z²³])")


def _question_part(s: str) -> str:
    s = re.sub(r"[(（][^()（）]*(?:取|热值|比热容|密度|g\s*=|ρ)[^()（）]*[)）]\s*[.。]?\s*$", "", s.strip())
    idx = max(s.rfind("求"), s.rfind("则"), -1)
    if idx >= 0:
        return s[idx:]
    ms = list(re.finditer(r"[^,;。，；]*(?:多少|多大|多长|多远|多高|多深|多重|多快|几)[^,;。，；]*", s))
    if ms:
        return ms[-1].group(0)
    # 没有明确问法时只看最后一个分句（以前取末尾 30 字，会把前面“…的速度…”当成所求，OCR 截断时乱答）
    parts = [p for p in re.split(r"[,;。，；\n]", s) if p.strip()]
    return parts[-1] if parts else ""


def _targets(s: str, roles: dict[str, Fraction]) -> list[str]:
    """所求量（按问句中出现的先后），最多 2 个（“求拉力做的功和功率”）。"""
    q = _question_part(s)
    found: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []
    for pat, name in _TARGETS:
        for m in re.finditer(pat, q):
            if any(m.start() < b and m.end() > a for a, b in taken):
                continue
            if name == "s" and re.search(r"深度|多深|高度|多高", m.group(0)):
                name = "h"
            if name in roles:  # 问的量题目已给出 → 不是所求
                continue
            taken.append((m.start(), m.end()))
            found.append((m.start(), name))
            break
    found.sort()
    out: list[str] = []
    for _, n in found:
        if n not in out:
            out.append(n)
    return out[:2]


# ── 公式表：(输出, 输入, 计算, 公式, 条件标志) ────────────────────────────────

Rule = tuple[str, tuple[str, ...], Callable[..., Fraction], str, str]


def _rules() -> list[Rule]:
    return [
        ("v", ("s", "t"), lambda s, t: s / t, "v = s/t", ""),
        ("s", ("v", "t"), lambda v, t: v * t, "s = vt", "not_echo"),
        ("s", ("v", "t"), lambda v, t: v * t / 2, "s = vt/2（回声：声音走了来回两倍路程）", "echo"),
        ("t", ("s", "v"), lambda s, v: s / v, "t = s/v", "not_echo"),
        ("rho", ("m", "V"), lambda m, V: m / V, "ρ = m/V", ""),
        ("m", ("rho", "V"), lambda r, V: r * V, "m = ρV", ""),
        ("V", ("m", "rho"), lambda m, r: m / r, "V = m/ρ", ""),
        ("G", ("m", "g"), lambda m, g: m * g, "G = mg", ""),
        ("m", ("G", "g"), lambda G, g: G / g, "m = G/g", ""),
        ("Fp", ("G",), lambda G: G, "物体放在水平面上，压力 F = G", "horizontal"),
        ("Fp", ("F",), lambda Fx: Fx, "压力 F", "press_force"),
        ("p", ("Fp", "S"), lambda Fx, S: Fx / S, "p = F/S", "solid"),
        ("Fp", ("p", "S"), lambda p, S: p * S, "F = pS", ""),
        ("S", ("Fp", "p"), lambda Fx, p: Fx / p, "S = F/p", ""),
        ("p", ("rho_l", "g", "h"), lambda r, g, h: r * g * h, "p = ρgh", "liquid"),
        ("h", ("p", "rho_l", "g"), lambda p, r, g: p / (r * g), "h = p/(ρg)", "liquid"),
        ("Ff", ("G", "Fs"), lambda G, Fs: G - Fs, "称重法：F浮 = G - F示", ""),
        ("Ff", ("G",), lambda G: G, "漂浮/悬浮：F浮 = G", "float"),
        ("Vp", ("V",), lambda V: V, "浸没时 V排 = V物", "immersed"),
        ("Ff", ("rho_l", "g", "Vp"), lambda r, g, V: r * g * V, "F浮 = ρ液gV排", ""),
        ("Vp", ("Ff", "rho_l", "g"), lambda Ff, r, g: Ff / (r * g), "V排 = F浮/(ρ液g)", ""),
        ("V", ("Vp",), lambda V: V, "浸没时 V物 = V排", "immersed"),
        ("rho_l", ("Ff", "g", "Vp"), lambda Ff, g, V: Ff / (g * V), "ρ液 = F浮/(gV排)", ""),
        ("F1", ("F2", "L2", "L1"), lambda F2, L2, L1: F2 * L2 / L1, "杠杆平衡条件 F₁L₁ = F₂L₂，F₁ = F₂L₂/L₁", ""),
        ("F2", ("F1", "L1", "L2"), lambda F1, L1, L2: F1 * L1 / L2, "F₁L₁ = F₂L₂，F₂ = F₁L₁/L₂", ""),
        ("L1", ("F2", "L2", "F1"), lambda F2, L2, F1: F2 * L2 / F1, "F₁L₁ = F₂L₂，L₁ = F₂L₂/F₁", ""),
        ("L2", ("F1", "L1", "F2"), lambda F1, L1, F2: F1 * L1 / F2, "F₁L₁ = F₂L₂，L₂ = F₁L₁/F₂", ""),
        ("F2", ("G",), lambda G: G, "阻力 F₂ = 物重 G", "lever_weight"),
        ("sr", ("n", "h"), lambda n, h: n * h, "s = nh", ""),
        ("Wu", ("G", "h"), lambda G, h: G * h, "W有 = Gh", "lift"),
        ("Wt", ("F", "sr"), lambda Fx, s: Fx * s, "W总 = Fs", ""),
        ("Wt", ("P", "t"), lambda P, t: P * t, "W总 = Pt", "pulley"),
        ("eta", ("Wu", "Wt"), lambda a, b: a / b, "η = W有/W总", ""),
        ("W", ("F", "s"), lambda Fx, s: Fx * s, "W = Fs", "not_lift"),
        ("W", ("G", "h"), lambda G, h: G * h, "W = Gh", "lift"),
        ("W", ("P", "t"), lambda P, t: P * t, "W = Pt", ""),
        ("P", ("W", "t"), lambda W, t: W / t, "P = W/t", ""),
        ("P", ("F", "v"), lambda Fx, v: Fx * v, "P = Fv", ""),
        ("F", ("P", "v"), lambda P, v: P / v, "F = P/v", ""),
        ("t", ("W", "P"), lambda W, P: W / P, "t = W/P", ""),
        ("dt", ("T1", "T2"), lambda a, b: b - a, "Δt = t末 - t初", ""),
        ("Q", ("c", "m", "dt"), lambda c, m, d: c * m * d, "Q = cmΔt", ""),
        ("dt", ("Q", "c", "m"), lambda Q, c, m: Q / (c * m), "Δt = Q/(cm)", ""),
        ("c", ("Q", "m", "dt"), lambda Q, m, d: Q / (m * d), "c = Q/(mΔt)", ""),
        ("m", ("Q", "c", "dt"), lambda Q, c, d: Q / (c * d), "m = Q/(cΔt)", ""),
        ("T2", ("T1", "dt"), lambda a, d: a + d, "t末 = t初 + Δt", ""),
        ("Qf", ("mf", "q"), lambda m, q: m * q, "Q放 = mq", ""),
        ("Qf", ("Vf", "qv"), lambda V, q: V * q, "Q放 = Vq", ""),
        ("mf", ("Qf", "q"), lambda Q, q: Q / q, "m = Q放/q", ""),
        ("Qf", ("Q", "eta"), lambda Q, e: Q / e, "Q放 = Q吸/η", "heat_eff"),
        ("eta", ("Q", "Qf"), lambda a, b: a / b, "η = Q吸/Q放", "heat_eff"),
        ("q", ("Qf", "mf"), lambda Q, m: Q / m, "q = Q放/m", ""),
        ("Q", ("Qf",), lambda Q: Q, "不计热损失 Q吸 = Q放", "no_loss"),
        ("R", ("R1", "R2"), lambda a, b: a + b, "串联：R = R₁ + R₂", "series"),
        ("R", ("R1", "R2"), lambda a, b: a * b / (a + b), "并联：R = R₁R₂/(R₁ + R₂)", "parallel"),
        ("I", ("U", "R"), lambda U, R: U / R, "I = U/R", ""),
        ("U", ("I", "R"), lambda cur, R: cur * R, "U = IR", ""),
        ("R", ("U", "I"), lambda U, cur: U / cur, "R = U/I", ""),
        ("I1", ("I",), lambda cur: cur, "串联电路电流处处相等", "series"),
        ("I2", ("I",), lambda cur: cur, "串联电路电流处处相等", "series"),
        ("I", ("I1",), lambda cur: cur, "串联电路电流处处相等", "series"),
        ("U1", ("I", "R1"), lambda cur, R: cur * R, "U₁ = IR₁", "series"),
        ("U2", ("I", "R2"), lambda cur, R: cur * R, "U₂ = IR₂", "series"),
        ("U1", ("U",), lambda U: U, "并联电路各支路电压相等", "parallel"),
        ("U2", ("U",), lambda U: U, "并联电路各支路电压相等", "parallel"),
        ("U", ("U1",), lambda U: U, "并联电路各支路电压相等", "parallel"),
        ("I1", ("U", "R1"), lambda U, R: U / R, "I₁ = U/R₁", "parallel"),
        ("I2", ("U", "R2"), lambda U, R: U / R, "I₂ = U/R₂", "parallel"),
        ("I", ("I1", "I2"), lambda a, b: a + b, "并联：I = I₁ + I₂", "parallel"),
        ("I", ("U1", "R1"), lambda U, R: U / R, "I = U₁/R₁", "series"),
        ("U", ("U1", "U2"), lambda a, b: a + b, "串联：U = U₁ + U₂", "series"),
        ("P", ("U", "I"), lambda U, cur: U * cur, "P = UI", "elec"),
        ("I", ("P", "U"), lambda P, U: P / U, "I = P/U", "elec"),
        ("R", ("U", "P"), lambda U, P: U * U / P, "R = U²/P", "elec"),
        ("P", ("U", "R"), lambda U, R: U * U / R, "P = U²/R", "elec"),
        ("We", ("P", "t"), lambda P, t: P * t, "W = Pt", "elec"),
        ("P", ("We", "t"), lambda W, t: W / t, "P = W/t", "elec"),
        ("t", ("We", "P"), lambda W, P: W / P, "t = W/P", "elec"),
        ("Qj", ("I", "R", "t"), lambda cur, R, t: cur * cur * R * t, "Q = I²Rt", ""),
        ("v", ("lam", "f"), lambda lm, f: lm * f, "v = λf", ""),
        ("lam", ("v", "f"), lambda v, f: v / f, "λ = v/f", ""),
        ("f", ("v", "lam"), lambda v, lm: v / lm, "f = v/λ", ""),
    ]


def _flags(s: str) -> dict[str, bool]:
    return {
        "fuel": bool(re.search(r"燃烧|热值|燃料", s)),
        "liquid": bool(re.search(r"深|液体|水下|水中|海水|水面下|液面下|容器底|水对|液体对|距水面|距液面", s)) and not re.search(r"桌面|地面|水平面上", s),
        "liq_p": bool(re.search(r"深|水下|水面下|液面下|距水面|距液面|液体压强|水的压强|容器底", s)) and bool(re.search(r"压强|压力", s)),
        "buoy": bool(re.search(r"浮力|浸没|浸在|浸入|漂浮|悬浮|排开", s)),
        "float": bool(re.search(r"漂浮|悬浮|浮在", s)),
        "immersed": bool(re.search(r"浸没|全部浸入|完全浸入|浸没在", s)),
        "horizontal": bool(re.search(r"水平(?:地面|桌面|面|台面|路面)|放在.{0,6}(?:地面|桌面)|静止在.{0,6}(?:地面|桌面)|站在|立在|压在|对地面|对桌面|对水平|与地面|停在", s)),
        "press_force": bool(re.search(r"压力(?:为|是|大小)", s)),
        "solid": not bool(re.search(r"深|液体对|水对容器底", s)) or bool(re.search(r"桌面|地面", s)),
        "lift": bool(re.search(r"提(?:升|高|起)|举高|举起|升高|吊起|匀速(?:竖直)?(?:向上)?拉|滑轮|搬到|运到.{0,4}楼|上楼", s)),
        "pulley": bool(re.search(r"滑轮", s)),
        "lever_weight": bool(re.search(r"杠杆|撬|扁担|跷跷板", s)) and not re.search(r"阻力(?:为|是)", s),
        "echo": bool(re.search(r"回声|反射回来|收到.{0,4}回波", s)),
        "heat_eff": bool(re.search(r"效率", s)) and bool(re.search(r"燃烧|热值", s)),
        "no_loss": bool(re.search(r"不计热(?:量)?损失|全部被.{0,4}吸收", s)),
        "series": bool(re.search(r"串联", s)),
        "parallel": bool(re.search(r"并联", s)),
        "elec": bool(re.search(r"电|灯|V\b|伏", s)),
    }


def _ok_cond(cond: str, fl: dict[str, bool]) -> bool:
    if not cond:
        return True
    if cond == "not_echo":
        return not fl["echo"]
    if cond == "not_lift":
        return not fl["lift"]
    return fl.get(cond, False)


def _fmt_q(name: str, v: Fraction) -> str:
    unit = _Q.get(name, ("", ""))[1]
    if name == "eta":
        return f"{fmt_sig(v * 100)}%"
    return f"{_sci(v)} {unit}".strip()


_SUPS = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def _pretty(raw: str) -> str:
    t = re.sub(r"\^\s*\(?\s*(-?\d+)\s*\)?", lambda m: m.group(1).translate(_SUPS), raw)
    return t.replace("*", "·")


def _sci(v: Fraction) -> str:
    av = abs(v)
    if av != 0 and (av >= 10**6 or av < F(1, 1000)):
        e = 0
        x = av
        while x >= 10:
            x /= 10
            e += 1
        while x < 1:
            x *= 10
            e -= 1
        mant = fmt_sig(x)
        return f"{'-' if v < 0 else ''}{mant}×10^{e}" if e >= 0 else f"{'-' if v < 0 else ''}{mant}×10^({e})"
    return fmt_sig(v)


_SYM = {"rho": "ρ", "rho_l": "ρ液", "Ff": "F浮", "Fs": "F示", "Vp": "V排", "Fp": "F压", "eta": "η", "lam": "λ", "dt": "Δt", "mf": "m燃料",
        "Vf": "V燃料", "Qf": "Q放", "Wu": "W有", "Wt": "W总", "We": "W电", "Qj": "Q", "sr": "s绳", "R1": "R₁", "R2": "R₂", "U1": "U₁",
        "U2": "U₂", "I1": "I₁", "I2": "I₂", "L1": "L₁", "L2": "L₂", "F1": "F₁", "F2": "F₂", "T1": "t初", "T2": "t末", "qv": "q"}


def _sym(n: str) -> str:
    return _SYM.get(n, n)


def solve_physics(text: str) -> Optional[KernelSolution]:
    s = basic_normalize(text).replace("·", "*").replace("•", "*")
    s = s.replace("°C", "℃").replace("摄氏度", "℃")
    s = re.sub(r"(\d)\s*度(?=电|,|，|。|$)", r"\1kW*h", s) if re.search(r"电能|电费|电表|用电", s) else s
    # 拍照 OCR 常把 m² 的上标丢掉：“接触面积是 0.25 m”——“面积”后紧跟的长度单位按面积单位读
    s = re.sub(r"(面积\s*(?:是|为|约|大约)?\s*\d+(?:\.\d+)?\s*(?:c|d|m)?m)(?![²³2^a-zA-Z/])", r"\1^2", s)
    toks = _tokens(s)
    if not toks:
        return None
    fl = _flags(s)
    roles: dict[str, Fraction] = {}
    known_desc: list[str] = []
    pre_steps: list[str] = []
    # 火车过桥/隧道：路程 = 车长 + 桥长
    if re.search(r"车长|(?:火车|列车|车队)(?:全)?长", s) and re.search(r"桥|隧道|山洞", s):
        lens = [t for t in toks if t.dim == "length"]
        if len(lens) == 2:
            tot = lens[0].value + lens[1].value
            roles["s"] = tot
            known_desc.append(f"s = 车长 + 桥(隧道)长 = {_fmt_q('s', lens[0].value)} + {_fmt_q('s', lens[1].value)} = {_fmt_q('s', tot)}")
            pre_steps.append("火车完全通过：从车头上桥到车尾离桥，走过的路程 = 车长 + 桥长")
            toks = [t for t in toks if t.dim != "length"]
    # “阻值分别为 a 和 b” → R1、R2（电压/电流同理）
    mpair = re.search(r"分别(?:为|是)\s*([\d.]+)\s*(Ω|V|A)\s*(?:和|、|与)\s*([\d.]+)\s*(Ω|V|A)", s)
    if mpair and mpair.group(2) == mpair.group(4):
        sym_ = {"Ω": "R", "V": "U", "A": "I"}[mpair.group(2)]
        v1, v2 = F(mpair.group(1)), F(mpair.group(3))
        roles[sym_ + "1"], roles[sym_ + "2"] = v1, v2
        known_desc.append(f"{_sym(sym_ + '1')} = {fmt_num(v1)} {mpair.group(2)}，{_sym(sym_ + '2')} = {fmt_num(v2)} {mpair.group(2)}")
        toks = [t for t in toks if not (mpair.start() <= t.start < mpair.end())]
    # 漂浮且有 a/b 体积露出：V排 = (1 - a/b)V
    mexp = re.search(r"有\s*(\d+)\s*/\s*(\d+)\s*的体积露出", s)
    if mexp:
        frac_out = F(int(mexp.group(1)), int(mexp.group(2)))
        vt = [t for t in toks if t.dim == "volume"]
        if len(vt) == 1 and 0 < frac_out < 1:
            roles["Vp"] = vt[0].value * (1 - frac_out)
            known_desc.append(f"V排 = (1 - {mexp.group(1)}/{mexp.group(2)}) × {_pretty(vt[0].raw)} = {_fmt_q('Vp', roles['Vp'])}")
            toks = [t for t in toks if t is not vt[0]]
            s = s[: mexp.start()] + " " * (mexp.end() - mexp.start()) + s[mexp.end():]
            fl["float"] = False
    for tok in toks:
        role = _role(s, tok, fl)
        if role is None:
            return None
        if role in roles and roles[role] != tok.value:
            # 同一角色两个不同数值（如两段路程）→ 不确定，不作答
            return None
        roles[role] = tok.value
        conv = "" if tok.unit in ("m", "s", "kg", "N", "Pa", "J", "W", "V", "A", "Ω", "m/s", "kg/m³", "m³", "m²", "℃", "Hz", "N/kg", "J/kg", "J/(kg·℃)", "%") \
            else f"（{_pretty(tok.raw)} = {_fmt_q(role, tok.value)}）"
        known_desc.append(f"{_sym(role)} = {_fmt_q(role, tok.value) if not conv else _pretty(tok.raw)}{conv}")
    # 题面里的裸数字（无单位）不能被忽略：除了题号/滑轮段数/“R1”下标外都必须有单位
    bare = [m for m in re.finditer(r"(?<![\w.^(])\d+(?:\.\d+)?(?![\w.%℃])", s) if not any(t.start <= m.start() < t.end for t in toks)
            and not (mpair and mpair.start() <= m.start() < mpair.end()) and not any(t.start <= m.start() < t.end for t in _tokens(s))]
    for m in bare:
        before = s[max(0, m.start() - 2):m.start()]
        after = s[m.end():m.end() + 2]
        if re.search(r"[RUIL]$", before) or re.match(r"\s*(?:段|根|股)", after) or re.match(r"\s*[.、]", after) and m.start() < 3:
            continue
        if re.match(r"\s*(?:倍|个|只|次|节|盏)", after):
            return None
        return None
    mn = re.search(r"(\d)\s*(?:段|股|根)(?:绳)?", s) if re.search(r"绳|滑轮", s) else None
    if mn:
        roles["n"] = F(mn.group(1))
        known_desc.append(f"n = {mn.group(1)}")
    if pre_steps:
        known_desc.insert(0, pre_steps[0])
    targets = _targets(s, roles)
    if not targets:
        return None
    if len(targets) == 2:
        first = _solve_one(s, text, dict(roles), list(known_desc), targets[0], fl, toks)
        second = _solve_one(s, text, dict(roles), list(known_desc), targets[1], fl, toks)
        if first is None or second is None:
            return first if second is None and first is not None and len(_targets(s, {})) < 2 else None
        steps = first.steps[:-1] + [st for st in second.steps[1:-1] if st not in first.steps] + [
            f"答：{first.steps[-1][2:]}；{second.steps[-1][2:]}"]
        return KernelSolution(
            kernel=first.kernel, answer=f"{first.answer}，{second.answer}", steps=steps, hint=first.hint, explanation=first.explanation,
            answer_value=f"{first.answer_value}, {second.answer_value}", answer_kind="nums", unit=f"{first.unit},{second.unit}",
            check=first.check, confidence=0.8,
        )
    return _solve_one(s, text, roles, known_desc, targets[0], fl, toks)


def _solve_one(s: str, text: str, roles: dict[str, Fraction], known_desc: list[str], target: str, fl: dict[str, bool],
               toks: list[_Tok]) -> Optional[KernelSolution]:
    # 常量
    consts: list[str] = []
    if "g" not in roles:
        roles["g"] = F(98, 10) if re.search(r"9\.8\s*N/kg|g\s*取\s*9\.8", s) else F(10)
        consts.append(f"g = {fmt_num(roles['g'])} N/kg")
    if (fl["liquid"] or fl["buoy"]) and "rho_l" not in roles:
        if "rho" in roles and not re.search(r"物体的?密度|木块的?密度|铁块的?密度|金属块的?密度", s):
            roles["rho_l"] = roles.pop("rho")
        elif re.search(r"水", s) and not re.search(r"酒精|煤油|盐水|海水|液体", s):
            roles["rho_l"] = F(1000)
            consts.append("ρ水 = 1.0×10³ kg/m³")
    if target in ("Q", "dt", "m", "T2", "eta", "Qf", "mf") and "c" not in roles and re.search(r"水", s) and re.search(r"热|温度|升高|加热|烧", s):
        roles["c"] = F(4200)
        consts.append("c水 = 4.2×10³ J/(kg·℃)")
    if target in ("s", "t", "v", "lam", "f") and "v" not in roles and target != "v":
        if re.search(r"光|电磁波|无线电|微波", s):
            roles["v"] = F(3 * 10**8)
            consts.append("光速 c = 3×10⁸ m/s")
        elif re.search(r"声|回声", s):
            roles["v"] = F(340)
            consts.append("声速 v = 340 m/s")
    if target == "Qf" and not fl["fuel"]:
        target = "Q"
    if target == "Qj" and not ("I" in roles or "U" in roles or "R" in roles):
        target = "Q"
    if target == "Q" and "Qj" not in roles and re.search(r"电流.{0,10}产生|电热|焦耳", s) and "I" in roles and "R" in roles:
        target = "Qj"
    if target == "W" and ("Wu" in roles or "Wt" in roles):
        return None
    if target == "W" and fl["elec"] and ("U" in roles or "I" in roles or "P" in roles and "F" not in roles):
        target = "We"
    if target == "P" and fl["lift"] and "Wt" not in roles and "W" not in roles and "F" in roles and "sr" in roles:
        pass
    # 前向推导
    steps_chain: list[tuple[str, str, Fraction]] = []
    outs: list[str] = []
    rules = _rules()
    known = dict(roles)
    for _ in range(12):
        if target in known:
            break
        progressed = False
        for out, ins, fn, formula, cond in rules:
            if out in known or not all(i in known for i in ins) or not _ok_cond(cond, fl):
                continue
            try:
                val = fn(*[known[i] for i in ins])
            except ZeroDivisionError:
                continue
            known[out] = val
            sub = "，".join(f"{_sym(i)} = {_fmt_q(i, known[i])}" for i in ins)
            steps_chain.append((formula, sub, val))
            outs.append(out)
            progressed = True
            if out == target:
                break
        if not progressed:
            break
    if target not in known:
        return None
    res = known[target]
    if res <= 0 and target not in ("dt",):
        return None
    if target == "eta" and not (0 < res <= 1):
        return None
    # 只保留通往目标的推导步骤
    needed = _needed(target, outs, steps_chain, rules, roles)
    steps = ["已知：" + "，".join(known_desc) + ("；" + "，".join(consts) if consts else "")]
    for (formula, sub, val), out in zip(steps_chain, outs):
        if out in needed:
            steps.append(f"由 {formula}：代入 {sub}，得 {_sym(out)} = {_fmt_q(out, val)}")
    # 题目要求的单位
    ans_unit = _Q.get(target, ("", ""))[1]
    disp_val = res
    mu = _ASK_UNIT.search(_question_part(s))
    if mu and target != "eta":
        dim, fac, udisp = _UNITS[mu.group(1)]
        if _dim_of(target) and dim != _dim_of(target) and not (target == "We" and dim == "energy"):
            return None  # 问的单位和所求量对不上（如“重力是多少吨”）：题意不明，不作答
        if _dim_of(target) == dim:
            disp_val = res / fac
            ans_unit = udisp
            steps.append(f"换算：{_fmt_q(target, res)} = {_sci(disp_val)} {udisp}")
    elif target == "We" and re.search(r"kW\*h|千瓦时|度", _question_part(s)):
        disp_val, ans_unit = res / 3600000, "kW·h"
        steps.append(f"换算：1 kW·h = 3.6×10⁶ J，W = {_sci(disp_val)} kW·h")
    if target == "eta":
        disp_val, ans_unit = res * 100, "%"
    approx = "约 " if _needs_round(disp_val) else ""
    name = _Q.get(target, (target, ""))[0]
    ans = f"{_sym(target) if target not in ('eta',) else 'η'} = {approx}{_sci(disp_val)} {ans_unit}".strip()
    steps.append(f"答：{name}为 {approx}{_sci(disp_val)} {ans_unit}".strip())
    # 复核：把结果代回最后一个公式的逆运算（数值一致）
    if not _recheck(target, known, rules, fl):
        return None
    return KernelSolution(
        kernel=f"physics.{_family(target, fl['heat_eff'])}",
        answer=ans,
        steps=steps,
        hint=_HINTS.get(_family(target, fl["heat_eff"]), "先把已知量换算成国际单位，找到联系已知量和所求量的公式，代入计算。"),
        explanation=f"{_EXPL.get(_family(target, fl['heat_eff']), '初中物理公式计算')}：已知 → 公式 → 代入 → 结果（注意单位统一）。",
        answer_value=fmt_num(disp_val, max_dec=6) if not _needs_round(disp_val) else fmt_sig(disp_val),
        answer_kind="num",
        unit=ans_unit,
        check="结果代回公式逆运算一致",
        confidence=0.85,
    )


def _needed(target: str, outs: list[str], chain: list, rules: list[Rule], roles: dict) -> set[str]:
    """反向找出推导目标真正用到的中间量。"""
    need = {target}
    by_out: dict[str, tuple[str, ...]] = {}
    for (formula, _sub, _v), out in zip(chain, outs):
        for o, ins, _fn, f2, _c in rules:
            if o == out and f2 == formula:
                by_out[out] = ins
                break
    stack = [target]
    while stack:
        cur = stack.pop()
        for i in by_out.get(cur, ()):
            if i not in need and i not in roles:
                need.add(i)
                stack.append(i)
    return need


def _recheck(target: str, known: dict[str, Fraction], rules: list[Rule], fl: dict[str, bool]) -> bool:
    """用另一个包含目标量的公式（若所有量已知）复核数值一致。"""
    for out, ins, fn, _f, cond in rules:
        if target in ins and out in known and all(i in known for i in ins) and _ok_cond(cond, fl):
            try:
                if fn(*[known[i] for i in ins]) != known[out]:
                    # 只要有一个公式不一致就说明角色识别有矛盾
                    if out not in ("Fp", "Ff", "Q", "Vp", "V", "F2", "I", "I1", "I2", "U", "U1", "U2", "R", "P", "W", "s", "t"):
                        continue
                    return False
            except ZeroDivisionError:
                continue
    return True


def _needs_round(v: Fraction) -> bool:
    d = v.denominator
    for p in (2, 5):
        while d % p == 0:
            d //= p
    if d != 1:
        return True
    return len(fmt_num(v, max_dec=12).split(".")[-1]) > 4 if "." in fmt_num(v, max_dec=12) else False


def _dim_of(name: str) -> str:
    return {"s": "length", "h": "length", "L1": "length", "L2": "length", "lam": "length", "sr": "length", "t": "time", "v": "speed",
            "m": "mass", "mf": "mass", "V": "volume", "Vp": "volume", "Vf": "volume", "rho": "density", "rho_l": "density",
            "G": "force", "F": "force", "Fp": "force", "Ff": "force", "Fs": "force", "F1": "force", "F2": "force", "S": "area",
            "p": "pressure", "W": "energy", "Wu": "energy", "Wt": "energy", "We": "energy", "Q": "energy", "Qf": "energy", "Qj": "energy",
            "P": "power", "U": "voltage", "U1": "voltage", "U2": "voltage", "I": "current", "I1": "current", "I2": "current",
            "R": "resistance", "R1": "resistance", "R2": "resistance", "f": "freq", "c": "c", "q": "q", "dt": "temp", "T2": "temp"}.get(name, "")


def _family(t: str, heat_eff: bool = False) -> str:
    if t == "eta" and heat_eff:
        return "heat"
    if t in ("v", "s", "t"):
        return "speed"
    if t in ("rho", "m", "V"):
        return "density"
    if t == "G":
        return "gravity"
    if t in ("p", "Fp", "S", "h"):
        return "pressure"
    if t in ("Ff", "Vp", "rho_l"):
        return "buoyancy"
    if t in ("F1", "F2", "L1", "L2"):
        return "lever"
    if t in ("W", "Wu", "Wt", "P", "eta", "F", "sr"):
        return "work_power"
    if t in ("Q", "dt", "c", "T2", "Qf", "mf", "q"):
        return "heat"
    if t in ("I", "U", "R", "I1", "I2", "U1", "U2", "R1", "R2"):
        return "ohm"
    if t in ("We", "Qj"):
        return "electric_power"
    if t in ("lam", "f"):
        return "wave"
    return "formula"


_HINTS = {
    "speed": "速度 = 路程 ÷ 时间；注意 1 m/s = 3.6 km/h，单位要统一。",
    "density": "密度 ρ = m/V；1 g/cm³ = 1.0×10³ kg/m³，代入前统一单位。",
    "gravity": "重力 G = mg，g 一般取 10 N/kg（题目说 9.8 就用 9.8）。",
    "pressure": "固体压强 p = F/S（水平面上 F = G）；液体压强 p = ρgh，h 是到液面的深度。面积要换成 m²。",
    "buoyancy": "浮力三种求法：称重法 F浮 = G - F示；阿基米德原理 F浮 = ρ液gV排；漂浮/悬浮 F浮 = G。",
    "lever": "杠杆平衡条件 F₁L₁ = F₂L₂，力臂是支点到力的作用线的距离。",
    "work_power": "W = Fs（力和在力的方向上移动的距离），P = W/t = Fv；η = W有/W总，滑轮组 s = nh。",
    "heat": "Q = cmΔt（Δt 是温度变化量，“升高到”要先减初温）；燃料 Q放 = mq；效率 = Q吸/Q放。",
    "ohm": "欧姆定律 I = U/R；串联电流相等、电阻相加；并联电压相等、电流相加。",
    "electric_power": "P = UI = U²/R = I²R，W = Pt（1 kW·h = 3.6×10⁶ J），焦耳热 Q = I²Rt。",
    "wave": "波速 v = λf；光速 3×10⁸ m/s，声速约 340 m/s，回声要除以 2。",
}
_EXPL = {
    "speed": "速度公式", "density": "密度公式", "gravity": "重力与质量的关系", "pressure": "压强", "buoyancy": "浮力",
    "lever": "杠杆平衡条件", "work_power": "功、功率与机械效率", "heat": "热量计算", "ohm": "欧姆定律与串并联电路",
    "electric_power": "电功率与电能", "wave": "波速与波长、频率",
}

__all__ = ["solve_physics"]
