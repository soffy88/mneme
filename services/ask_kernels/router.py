"""拍照问题目的确定性路由（无 LLM）。

classify(text) 用正则 + 关键词给每个内核族打分，按分数从高到低依次尝试；
第一个返回“已验证 + 置信度 ≥ 0.6”的解即为结果。纯数学内核（算术、方程、不等式、整式）
额外要求题面除了式子以外没有“应用题/物理/化学”的领域词，避免把物理题里的 2×10³ 当成计算题作答。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

from services.ask_kernels import algebra, arith, functions, geometry, stats, word
from services.ask_kernels.core import KernelSolution, basic_normalize, latex_to_plain, strip_question_number
from services.ask_kernels.sym import math_normalize, segments

MIN_CONFIDENCE = 0.6

Solver = Callable[[str], Optional[KernelSolution]]


@dataclass(frozen=True)
class KernelSpec:
    name: str
    fn: Solver
    family: str  # chem | physics | word | geometry | function | stats | algebra | arith
    keywords: str  # 命中则加分的关键词正则
    base: float


def _physics(text: str) -> Optional[KernelSolution]:
    try:
        from services.ask_kernels.physics import solve_physics
    except ImportError:
        return None
    return solve_physics(text)


def _chem_calc(text: str) -> Optional[KernelSolution]:
    try:
        from services.ask_kernels.chemistry import solve_chemistry_calc
    except ImportError:
        return None
    return solve_chemistry_calc(text)


_PHYS_KW = r"速度|密度|重力|压强|压力|浮力|杠杆|力臂|功率|机械效率|做功|做了多少功|比热容|热值|热量|吸收|放出|电阻|电压|电流|电功|电能|电功率|焦耳|欧姆|串联|并联|灯泡|kW·h|千瓦时|波长|频率|光速|声速|回声|牛顿|\d\s*N\b|\d\s*Pa\b|\d\s*Ω|\d\s*V\b|\d\s*A\b|\d\s*W\b|\d\s*J\b|kg/m|g/cm|m/s|km/h|℃"
_CHEM_KW = r"相对分子质量|相对原子质量|质量分数|溶质|溶液|化学式|化学方程式|生成|反应|配平|[A-Z][a-z]?\d*\s*[+=→]|克.*?[A-Z][a-z]?\d"
_WORD_KW = r"相遇|相向|追上|追及|环形|工程|单独|合作|进价|标价|售价|利润|打.?折|折出售|浓度|盐水|糖水|岁|年龄|鸡|兔"
_GEO_KW = r"三角形|△|直角|勾股|斜边|圆|扇形|弧长|半径|直径|边形|内角|外角|相似|∽|梯形|平行四边形|长方形|正方形|矩形|面积|周长|sin|cos|tan"
_FUNC_KW = r"函数|抛物线|顶点|对称轴|图象|直线\s*y"
_STAT_KW = r"平均数|中位数|众数|方差|标准差|极差|概率|可能性|骰子|硬币|摸|按.{0,3}\d+\s*:\s*\d+|增长率|百分之几|解比例|=\s*\(\s*\)|=\s*（\s*）"
_ALG_KW = r"方程|不等式|因式分解|分解因式|化简|展开|配方|整数解|根"

def _chem_balance(text: str) -> Optional[KernelSolution]:
    from services.ask_kernels.chemistry import solve_balance

    return solve_balance(text)


KERNELS: list[KernelSpec] = [
    KernelSpec("chemistry.calc", _chem_calc, "chem", _CHEM_KW, 0.5),
    KernelSpec("chemistry.balance", _chem_balance, "chem", r"配平|化学计量数", 0.5),
    KernelSpec("physics", _physics, "physics", _PHYS_KW, 0.5),
    KernelSpec("word.chicken_rabbit", word.solve_chicken_rabbit, "word", r"鸡|兔", 0.6),
    KernelSpec("word.travel", word.solve_travel, "word", r"相遇|相向|追上|追及|环形|跑道", 0.6),
    KernelSpec("word.work", word.solve_work, "word", r"工程|单独|合作|注满", 0.6),
    KernelSpec("word.profit", word.solve_profit, "word", r"进价|标价|售价|利润|折", 0.6),
    KernelSpec("word.concentration", word.solve_concentration, "word", r"浓度|盐水|糖水|含盐|含糖", 0.6),
    KernelSpec("word.age", word.solve_age, "word", r"岁|年龄", 0.6),
    KernelSpec("geometry.right_triangle_trig", geometry.solve_right_triangle_trig, "geometry", r"Rt|∠.{0,3}=\s*90", 0.55),
    KernelSpec("geometry.pythagoras", geometry.solve_pythagoras, "geometry", r"直角三角形|勾股|斜边|Rt", 0.55),
    KernelSpec("geometry.circle", geometry.solve_circle, "geometry", r"圆|扇形|弧", 0.5),
    KernelSpec("geometry.polygon", geometry.solve_polygon_angles, "geometry", r"边形", 0.55),
    KernelSpec("geometry.similar", geometry.solve_similar, "geometry", r"相似|∽", 0.55),
    KernelSpec("geometry.triangle_angles", geometry.solve_triangle_angles, "geometry", r"内角|顶角|底角|°", 0.45),
    KernelSpec("geometry.plane", geometry.solve_plane_figure, "geometry", r"面积|周长", 0.4),
    KernelSpec("function.quadratic", functions.solve_quadratic_function, "function", r"二次函数|抛物线", 0.6),
    KernelSpec("function.inverse", functions.solve_inverse_proportion, "function", r"反比例", 0.6),
    KernelSpec("function.linear", functions.solve_linear_function, "function", r"一次函数|正比例|直线", 0.55),
    KernelSpec("stats.descriptive", stats.solve_statistics, "stats", r"平均|中位数|众数|方差|标准差|极差", 0.55),
    KernelSpec("prob", stats.solve_probability, "stats", r"概率|可能性", 0.55),
    KernelSpec("ratio", stats.solve_ratio_percent, "stats", r"比例|分配|百分|增长率|下降率|:", 0.45),
    KernelSpec("unit.convert", stats.solve_unit_conversion, "stats", r"=\s*[(（_?]", 0.45),
    KernelSpec("algebra.quadratic_param", algebra.solve_quadratic_param, "algebra", r"关于\s*[a-z]\s*的", 0.5),
    KernelSpec("algebra.vieta", algebra.solve_vieta, "algebra", r"[a-z]\s*1|[a-z]₁|两根|根的情况|判别式", 0.5),
    KernelSpec("algebra.linear_system", algebra.solve_linear_system, "algebra", r"方程组|\{", 0.45),
    KernelSpec("algebra.inequality", algebra.solve_inequality, "algebra", r"不等式|[<>≤≥]", 0.45),
    KernelSpec("algebra.polynomial", algebra.solve_polynomial, "algebra", r"因式分解|分解因式|化简|展开|配方|求值", 0.45),
    KernelSpec("algebra.equation", algebra.solve_equation_1var, "algebra", r"方程|=", 0.4),
    KernelSpec("arith.sci", arith.solve_sci, "arith", r"科学记数法|科学计数法", 0.5),
    KernelSpec("arith.compare", arith.solve_compare, "arith", r"比较|哪个大|哪个小", 0.5),
    KernelSpec("arith", arith.solve_arithmetic, "arith", r"计算|求值|=\s*$|=\s*\?", 0.35),
]

# 纯数学内核：题面除式子外不应出现这些领域词
_DOMAIN_WORDS = re.compile(
    r"千米|公里|米(?!的)|厘米|克|千克|吨|(?<![一二三四])元(?!一次|二次)|小时|分钟|秒|速度|质量|密度|压强|浮力|电阻|电压|电流|功率|温度|溶液|浓度|"
    r"溶质|甲|乙|人|天|岁|件|辆|车|水|盐|价|利润|买|卖|面积|周长|半径|直径|三角形|△|圆|边形|长方|正方|函数|概率|平均|"
    r"体积|容积|物体|木块|铁块|灯|电路|加热|燃烧|反应|生成|物质"
)
_PURE_FAMILIES = {"algebra", "arith"}


def _residual_ok(text: str) -> bool:
    s = math_normalize(text)
    rest = s
    for seg in segments(s, need_digit=False):
        rest = rest.replace(seg, " ")
    return not _DOMAIN_WORDS.search(rest)


def classify(text: str, subject: Optional[str] = None) -> list[tuple[float, KernelSpec]]:
    """返回 (分数, 内核) 列表，按分数降序。分数只决定尝试顺序；最终以验证结果为准。"""
    raw = basic_normalize(text)
    fam_bonus: dict[str, float] = {}
    for fam, kw in (("physics", _PHYS_KW), ("chem", _CHEM_KW), ("word", _WORD_KW), ("geometry", _GEO_KW),
                    ("function", _FUNC_KW), ("stats", _STAT_KW), ("algebra", _ALG_KW)):
        n = len(re.findall(kw, raw))
        if n:
            fam_bonus[fam] = min(0.3, 0.1 * n)
    if subject in ("physics", "物理"):
        fam_bonus["physics"] = fam_bonus.get("physics", 0) + 0.3
    elif subject in ("chemistry", "化学"):
        fam_bonus["chem"] = fam_bonus.get("chem", 0) + 0.3
    scored = []
    for spec in KERNELS:
        sc = spec.base + fam_bonus.get(spec.family, 0.0)
        if re.search(spec.keywords, raw):
            sc += 0.2
        scored.append((round(sc, 3), spec))
    scored.sort(key=lambda t: -t[0])
    return scored


def solve_text(text: str, subject: Optional[str] = None, *, budget_s: float = 4.0,
               families: Optional[set[str]] = None) -> Optional[KernelSolution]:
    """同步求解（CPU 轻量）：按分类顺序尝试，返回第一个已验证、置信的解；都不行返回 None。"""
    t = strip_question_number(latex_to_plain((text or "").strip()))
    if not t or len(t) > 1500:
        return None
    t0 = time.monotonic()
    pure_ok: Optional[bool] = None
    for _score, spec in classify(t, subject):
        if families is not None and spec.family not in families:
            continue
        if time.monotonic() - t0 > budget_s:
            break
        if spec.family in _PURE_FAMILIES:
            if pure_ok is None:
                pure_ok = _residual_ok(t)
            if not pure_ok:
                continue
        try:
            sol = spec.fn(t)
        except Exception:  # noqa: BLE001 — 单个内核出错不影响其他内核
            sol = None
        if sol is not None and sol.verified and sol.confidence >= MIN_CONFIDENCE and (sol.answer or "").strip():
            if off_target(t, sol):
                continue
            return _as_percent_if_asked(t, sol)
    return None


# ── 答非所问守卫 ───────────────────────────────────────────────────────────
# 题库扫描（bank_scan）里内核“解对了一个式子、却不是题目问的东西”的典型情形：问估算、问代数式的值、
# 已知概率反求个数、半圆/圆环/剪去、区间最值、超纲（对数/双曲线/参数方程）……这些一律弃答，宁缺毋滥。

_ABSTAIN_ALL = re.compile(
    r"大约|估算|估一估|估计|近似解|二分法|密码|参数方程|极坐标|对数|log|\blg\b|焦点|双曲线|椭圆|弧度|向量|数列|"
    r"如图|如右图|如下图|图中|阴影|<ImageHere>|机器人|依次计算|从左到右|算成|看成|抄错|漏掉|"
    r"互为倒数|内项|外项|四棱|棱锥|棱柱|表面积|\.\.\.|…|⋯|∈"
)
_EQ_KERNELS = ("algebra.linear_eq", "algebra.quadratic_eq", "algebra.abs_eq", "algebra.fractional_eq",
               "algebra.linear_system")
_ASK_VALUE = re.compile(r"(?:则|求|那么|式子|代数式|计算)\s*(?:代数式|式子)?\s*([^,;。?，；]{1,60}?)\s*(?:的值|值为|值是|=\s*(?:（\s*）)?\s*[.。]?\s*$)")


def _asked_expression(raw: str) -> Optional[str]:
    """“则 3m^2-12m+2020 的值为”里被问的式子（不是单个字母）；没有返回 None。"""
    for m in _ASK_VALUE.finditer(raw):
        e = m.group(1).strip()
        if re.search(r"[a-z]", e) and not re.fullmatch(r"[a-z]", e) and re.search(r"[+\-*/^()]|\d\s*[a-z]|[a-z]\s*[a-z]", e):
            return e
    return None


def _asked_var(raw: str) -> Optional[str]:
    m = re.search(r"(?:则|求|那么)?\s*(?:实数|整数)?\s*([a-z])\s*(?:的(?:最大|最小)?(?:整数)?(?:值|解)|\s*=\s*(?:（\s*）|\?|$))", raw)
    return m.group(1) if m else None


def off_target(text: str, sol: KernelSolution) -> bool:
    """内核给出的解是否答非所问（True → 弃答）。只做排除，不改答案。"""
    raw = basic_normalize(text)
    k = sol.kernel
    fam = k.split(".")[0]
    if _ABSTAIN_ALL.search(raw):
        return True
    if re.search(r"(?:sin|cos|tan)", raw) and fam == "arith" and re.search(r"(?:sin|cos|tan)(?!\s*(?:\^\s*\d)?\s*\(?\s*\d+(?:\.\d+)?\s*°)", raw):
        return True  # 只认特殊角“sin30°”；sin(13π/6) 之类不作答
    if re.search(r"sin|cos|tan|log", sol.answer_value or ""):
        return True
    if k.startswith(_EQ_KERNELS) or k in ("function.linear", "function.quadratic"):
        if _asked_expression(raw):
            return True  # 解出了方程，题目问的却是另一个代数式的值
        v = _asked_var(raw)
        got_vars = set(re.findall(r"([a-z])\s*=", sol.answer_value or ""))
        if v and got_vars and v not in got_vars:
            return True
        if v and k.startswith("function.") and sol.answer_kind == "expr" and v not in got_vars:
            return True  # 问参数的值，内核却给了函数解析式
    if k.startswith(_EQ_KERNELS) and re.search(r"当\s*[a-z]\s*=", raw):
        return True  # “当 x=√3+1 时，式子…的值”是代入求值，不是解方程
    if fam == "prob" and re.search(r"(?:概率|可能性)\s*(?:为|是|等于)\s*[(\d]", raw):
        return True  # 已知概率反求个数/参数
    if fam == "stats" and re.search(r"[的之](?:差|和|积|商)|相差|多多少|少多少", raw) and "," in (sol.answer_value or ""):
        return True
    if k.startswith("function.quadratic") and re.search(r"[≤<]\s*x\s*[≤<]|二次项|一次项|常数项|△|三角形|面积|温度|整数", raw):
        return True
    if k == "algebra.vieta" and re.search(r"s\s*\^\s*2|方差", raw):
        return True
    if k.startswith("geometry.circle") and re.search(r"增加|减少|扩大|缩小|内切|外接|△|三角形|圆环|环形|剪|剩下|最大|中心角|画|转化|拼成|长方形|正方形", raw):
        return True
    if k.startswith(("geometry.rectangle", "geometry.square", "geometry.plane")) and re.search(
        r"圆|放大|缩小|比例|剪|剩下|小路|折|拼|围成|做成|制成", raw):
        return True
    if fam == "arith" and k != "arith.sci" and re.search(r"[(（]\s*[)）]\s*[里内]?填|[□○]", raw) and not re.search(r"计算|=", raw):
        return True
    return False


def _as_percent_if_asked(text: str, sol: KernelSolution) -> KernelSolution:
    """题目要求“填百分号前的数/用百分数表示”而内核给的是小数/分数 → 换成百分数。"""
    from fractions import Fraction

    raw = basic_normalize(text)
    if sol.answer_kind != "num" or sol.unit == "%" or not re.search(r"百分号前|百分数前|用百分数表示|写成百分数|百分率是多少", raw):
        return sol
    try:
        v = Fraction(sol.answer_value)
    except (ValueError, ZeroDivisionError):
        return sol
    pct = v * 100
    if re.search(r"保留整数|取整", raw):
        val = str(round(pct))
    elif pct.denominator == 1 or len(str(float(pct)).split(".")[-1]) <= 2:
        val = str(float(pct)).rstrip("0").rstrip(".")
    else:
        val = f"{float(pct):.1f}"
    sol.steps.append(f"化成百分数：{sol.answer_value} = {val}%")
    sol.answer = f"{val}%"
    sol.answer_value = val
    sol.unit = "%"
    return sol


# ── 多题图片拆分 ─────────────────────────────────────────────────────────────

_TOP = re.compile(r"(?:(?<=\n)|^|(?<=\s{2})|(?<=[。.;；!?！？]\s)|(?<=[。;；!?！？]))\s*(\d{1,2})\s*[.、．](?!\d)\s*")
_SUB = re.compile(r"[(（]\s*(\d{1,2})\s*[)）]|([①②③④⑤⑥⑦⑧⑨⑩])")
_CIRC = "①②③④⑤⑥⑦⑧⑨⑩"


def split_questions(text: str) -> list[dict]:
    """把一张图里的多道题拆开。返回 [{index, label, text}]；不足两题返回 []。

    - 顶层题号：行首（或空两格后）的“1.”“2、”，编号必须从小到大连续；
    - 小题：“(1)(2)”或“①②”，有公共题干时把题干拼到每个小题前面。
    """
    s = (text or "").replace("\r", "\n")
    s = "".join(chr(ord(c) - 0xFEE0) if 0xFF10 <= ord(c) <= 0xFF19 else c for c in s).replace("．", ".")
    tops = list(_TOP.finditer(s))
    if len(tops) >= 2:
        nums = [int(m.group(1)) for m in tops]
        if all(b == a + 1 for a, b in zip(nums, nums[1:])):
            out: list[dict] = []
            for i, m in enumerate(tops):
                end = tops[i + 1].start() if i + 1 < len(tops) else len(s)
                body = s[m.end():end].strip()
                if body:
                    out.append({"index": len(out), "label": m.group(1), "text": body})
            if len(out) >= 2:
                return out
    subs = list(_SUB.finditer(s))
    if len(subs) >= 2:
        labels = [int(m.group(1)) if m.group(1) else _CIRC.index(m.group(2)) + 1 for m in subs]
        if labels[0] == 1 and all(b == a + 1 for a, b in zip(labels, labels[1:])):
            stem = s[: subs[0].start()].strip()
            out = []
            for i, m in enumerate(subs):
                end = subs[i + 1].start() if i + 1 < len(subs) else len(s)
                body = s[m.end():end].strip(" ;；,，\n")
                if not body:
                    continue
                full = f"{stem} {body}".strip() if stem and len(stem) < 400 else body
                out.append({"index": len(out), "label": f"({labels[i]})", "text": full, "part": body})
            if len(out) >= 2:
                return out
    return []


__all__ = ["KERNELS", "KernelSpec", "MIN_CONFIDENCE", "classify", "off_target", "solve_text", "split_questions"]
