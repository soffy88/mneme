"""统计与概率、比例与百分率、单位换算。全部用 Fraction 精确计算。"""

from __future__ import annotations

import itertools
import math
import re
from collections import Counter
from fractions import Fraction
from typing import Optional

from services.ask_kernels.core import KernelSolution, basic_normalize, cn_small_number, fmt_approx, fmt_num

F = Fraction


def _fmt(v: Fraction) -> str:
    return fmt_num(v, max_dec=4)


def _sqrt_str(v: Fraction) -> tuple[str, str]:
    """√v 的精确写法 + 机器值。"""
    import sympy as sp

    r = sp.sqrt(sp.Rational(v.numerator, v.denominator))
    from services.ask_kernels.sym import fmt, value_str

    return fmt(r), value_str(r)


# ── 统计 ─────────────────────────────────────────────────────────────────────

_STAT_WORDS = [
    ("mean", r"平均数|平均值|平均分|平均成绩|平均"),
    ("median", r"中位数"),
    ("mode", r"众数"),
    ("var", r"方差"),
    ("std", r"标准差"),
    ("range", r"极差"),
]


def _data_list(raw: str) -> Optional[list[Fraction]]:
    m = re.search(r"(?:数据|一组数|成绩|分数|如下|分别为|分别是|依次为|依次是|为|是|:)\s*[:：]?\s*((?:-?\d+(?:\.\d+)?\s*[,、，\s]\s*){2,}-?\d+(?:\.\d+)?)", raw)
    if not m:
        return None
    nums = re.findall(r"-?\d+(?:\.\d+)?", m.group(1))
    if len(nums) < 3 or len(nums) > 60:
        return None
    return [F(x) for x in nums]


def solve_statistics(text: str) -> Optional[KernelSolution]:
    raw = basic_normalize(text)
    asks = [(m.start(), k) for k, pat in _STAT_WORDS for m in [re.search(pat, raw)] if m]
    if not asks:
        return None
    asks.sort()
    keys = [k for _, k in asks]
    if "std" in keys and "var" in keys and raw.find("方差") > raw.find("标准差") >= 0:
        pass
    # 加权平均：“按 3:3:4 的比例”/“权重”
    wm = re.search(r"(\d+(?:\.\d+)?)\s*[:：]\s*(\d+(?:\.\d+)?)(?:\s*[:：]\s*(\d+(?:\.\d+)?))?(?:\s*[:：]\s*(\d+(?:\.\d+)?))?\s*(?:的比例|的权|的比|计算|确定)", raw)
    if keys[:1] == ["mean"] and re.search(r"权重相同|权重一样|权重相等|同等权重", raw):
        sc = [F(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*(?:分)?(?=[,，、。\s]|$)", raw)]
        cnt = re.search(r"([二三四五六七八九两])(?:门|科|项)", raw)
        if sc and cnt and cn_small_number(cnt.group(1)) == len(sc):
            res = sum(sc, F(0)) / len(sc)
            return KernelSolution(kernel="stats.weighted_mean", answer=_fmt(res), steps=[f"权重相同时加权平均数就是算术平均数：({' + '.join(_fmt(x) for x in sc)}) ÷ {len(sc)} = {_fmt(res)}"],
                                  hint="权重相同，加权平均数 = 算术平均数。", explanation="加权平均数。", answer_value=fmt_num(res, max_dec=8), answer_kind="num", check="复算")
    if wm and keys[:1] == ["mean"]:
        weights = [F(x) for x in wm.groups() if x]
        before = raw[: wm.start()]
        scores = [F(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*分", before)]
        if len(scores) != len(weights):
            scores = [F(x) for x in re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)(?![\d.]*\s*[:：%])", before)]
            scores = scores[-len(weights):] if len(scores) >= len(weights) else scores
        if len(scores) != len(weights):
            return None
        tot = sum((s * w for s, w in zip(scores, weights)), F(0))
        res = tot / sum(weights, F(0))
        steps = ["加权平均数 = (各数 × 权) 之和 ÷ 权之和",
                 " + ".join(f"{_fmt(s)}×{_fmt(w)}" for s, w in zip(scores, weights)) + f" = {_fmt(tot)}",
                 f"{_fmt(tot)} ÷ {_fmt(sum(weights, F(0)))} = {_fmt(res)}"]
        return KernelSolution(
            kernel="stats.weighted_mean", answer=_fmt(res), steps=steps,
            hint="加权平均数 = Σ(数据×权) ÷ Σ权，权就是题目给的比例或百分比。",
            explanation="加权平均数。", answer_value=fmt_num(res, max_dec=8), answer_kind="num", check="Σ权×(x-平均)=0",
        ) if sum((w * (s - res) for s, w in zip(scores, weights)), F(0)) == 0 else None
    data = _data_list(raw)
    if data is None:
        return None
    n = len(data)
    steps = [f"数据共 {n} 个：" + "、".join(_fmt(x) for x in data)]
    vals: list[str] = []
    parts: list[str] = []
    mean = sum(data, F(0)) / n
    var = sum(((x - mean) ** 2 for x in data), F(0)) / n
    for k in dict.fromkeys(keys):
        if k == "mean":
            steps.append(f"平均数 = ({' + '.join(_fmt(x) for x in data)}) ÷ {n} = {_fmt(sum(data, F(0)))} ÷ {n} = {_fmt(mean)}")
            parts.append(f"平均数 {_fmt(mean)}")
            vals.append(fmt_num(mean, max_dec=8))
        elif k == "median":
            srt = sorted(data)
            med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
            steps.append("从小到大排列：" + "、".join(_fmt(x) for x in srt))
            steps.append(f"中位数 = {'第 %d 个数' % (n // 2 + 1) if n % 2 else '中间两个数的平均数'} = {_fmt(med)}")
            parts.append(f"中位数 {_fmt(med)}")
            vals.append(fmt_num(med, max_dec=8))
        elif k == "mode":
            c = Counter(data)
            top = max(c.values())
            if top == 1:
                steps.append("每个数据都只出现一次，没有众数")
                parts.append("没有众数")
                vals.append("无")
                continue
            modes = sorted(x for x, v in c.items() if v == top)
            steps.append(f"出现次数最多（{top} 次）的数据是 " + "、".join(_fmt(x) for x in modes))
            parts.append("众数 " + "、".join(_fmt(x) for x in modes))
            vals += [fmt_num(x, max_dec=8) for x in modes]
        elif k in ("var", "std"):
            steps.append(f"平均数 x̄ = {_fmt(mean)}")
            steps.append("方差 s² = [" + " + ".join(f"({_fmt(x)}-{_fmt(mean)})²" for x in data[:8]) + (" + …" if n > 8 else "") + f"] ÷ {n} = {_fmt(var)}")
            if k == "var":
                parts.append(f"方差 {_fmt(var)}")
                vals.append(fmt_num(var, max_dec=8))
            else:
                sd, sdv = _sqrt_str(var)
                steps.append(f"标准差 s = √{_fmt(var)} = {sd}" + ("" if "√" not in sd else f"（≈ {fmt_approx(F(math.sqrt(var)), 4)}）"))
                parts.append(f"标准差 {sd}")
                vals.append(sdv)
        elif k == "range":
            rg = max(data) - min(data)
            steps.append(f"极差 = 最大值 - 最小值 = {_fmt(max(data))} - {_fmt(min(data))} = {_fmt(rg)}")
            parts.append(f"极差 {_fmt(rg)}")
            vals.append(fmt_num(rg, max_dec=8))
    if not vals:
        return None
    return KernelSolution(
        kernel="stats.descriptive", answer="，".join(parts), steps=steps,
        hint="中位数要先排序；众数看出现次数最多的；方差 = 各数据与平均数之差的平方的平均数。",
        explanation="数据的集中趋势与离散程度。", answer_value=", ".join(vals),
        answer_kind="nums" if len(vals) > 1 else "num", check="平均数复算一致",
    )


# ── 概率 ─────────────────────────────────────────────────────────────────────

_COLORS = "红|白|黑|黄|绿|蓝|紫|橙|灰|粉"


def _cond_ok(x: int, cond: str) -> Optional[bool]:
    m = re.search(r"大于\s*(\d+)", cond)
    if m:
        return x > int(m.group(1))
    m = re.search(r"小于\s*(\d+)", cond)
    if m:
        return x < int(m.group(1))
    m = re.search(r"不(?:大于|超过)\s*(\d+)", cond)
    if m:
        return x <= int(m.group(1))
    m = re.search(r"不小于\s*(\d+)", cond)
    if m:
        return x >= int(m.group(1))
    m = re.search(r"(\d+)\s*的倍数", cond)
    if m:
        return x % int(m.group(1)) == 0
    if "偶数" in cond:
        return x % 2 == 0
    if "奇数" in cond:
        return x % 2 == 1
    if "质数" in cond or "素数" in cond:
        return x > 1 and all(x % d for d in range(2, int(math.isqrt(x)) + 1))
    if "合数" in cond:
        return x > 3 and any(x % d == 0 for d in range(2, int(math.isqrt(x)) + 1))
    m = re.search(r"(?:是|为|等于)\s*(\d+)(?!\s*的倍数)", cond)
    if m:
        return x == int(m.group(1))
    return None


def solve_probability(text: str) -> Optional[KernelSolution]:
    raw = basic_normalize(text)
    if not re.search(r"概率|可能性", raw):
        return None
    hint = "古典概型：P = 满足条件的结果数 ÷ 所有等可能的结果数；两步试验用列表或树状图列全。"
    expl = "简单随机事件的概率。"
    # 1) 摸球
    balls = re.findall(rf"(\d+|[一二三四五六七八九十两]+)\s*(?:个|只)\s*({_COLORS})(?:色)?\s*(?:球|的球|小球)?", raw)
    if balls and re.search(r"球", raw) and not re.search(r"两次|再摸|放回|两个球|2个球|同时摸出", raw):
        counts: dict[str, int] = {}
        for nstr, col in balls:
            nn = int(nstr) if nstr.isdigit() else cn_small_number(nstr)
            if nn is None:
                return None
            counts[col] = counts.get(col, 0) + nn
        target = re.search(rf"(?:摸到|摸出|取出|取到|是)\s*({_COLORS})(?:色)?\s*(?:球|的)", raw[raw.find("摸") if "摸" in raw else 0:])
        if not target or target.group(1) not in counts:
            return None
        tot = sum(counts.values())
        k = counts[target.group(1)]
        p = F(k, tot)
        steps = ["袋中共有 " + " + ".join(f"{v} 个{c}球" for c, v in counts.items()) + f" = {tot} 个球，每个球被摸到的可能性相同",
                 f"{target.group(1)}球有 {k} 个，P = {k}/{tot} = {fmt_num(p, max_dec=0)}"]
        return KernelSolution(kernel="prob.classical", answer=fmt_num(p, max_dec=0), steps=steps, hint=hint, explanation=expl,
                              answer_value=f"{p.numerator}/{p.denominator}" if p.denominator != 1 else str(p.numerator), answer_kind="num", check="枚举计数")
    # 2) 掷一枚骰子 / 从 1~n 中任取一个数
    die = re.search(r"(?:掷|抛)\s*(?:一枚|一个|1枚)\s*(?:质地均匀的)?\s*(?:正方体)?骰子", raw)
    two_dice = re.search(r"(?:掷|抛)\s*(?:两枚|两个|2枚)\s*(?:质地均匀的)?\s*骰子|(?:掷|抛)\s*(?:一枚)?\s*骰子\s*两次", raw)
    rng = re.search(r"从\s*(\d+)\s*(?:~|～|-|到|至)\s*(\d+)\s*(?:这\s*\d+\s*个(?:整数|数)|中|的整数中|共)", raw) or re.search(
        r"(?:标有|写有|分别写有|分别标有)\s*(\d+)\s*(?:~|～|-|到|至)\s*(\d+)\s*的?.{0,6}?(?:卡片|小球|球|纸条|签)", raw)
    if two_dice:
        m = re.search(r"(?:点数)?(?:之和|的和)\s*(?:为|是|等于)\s*(\d+)", raw)
        outcomes = list(itertools.product(range(1, 7), repeat=2))
        if m:
            target_sum = int(m.group(1))
            good = [o for o in outcomes if sum(o) == target_sum]
            desc = f"点数之和为 {target_sum}"
        elif re.search(r"点数相同|点数相等", raw):
            good = [o for o in outcomes if o[0] == o[1]]
            desc = "点数相同"
        else:
            return None
        p = F(len(good), 36)
        steps = ["列表法：两枚骰子共有 6×6 = 36 种等可能的结果",
                 f"{desc}的有 {len(good)} 种：" + "、".join(f"({a},{b})" for a, b in good[:12]),
                 f"P = {len(good)}/36 = {fmt_num(p, max_dec=0)}"]
        return KernelSolution(kernel="prob.two_step", answer=fmt_num(p, max_dec=0), steps=steps, hint=hint, explanation=expl,
                              answer_value=f"{p.numerator}/{p.denominator}" if p.denominator != 1 else str(p.numerator), answer_kind="num", check="列表枚举")
    if die or rng:
        lo, hi = (1, 6) if die else (int(rng.group(1)), int(rng.group(2)))  # type: ignore[union-attr]
        if hi - lo > 200 or hi < lo:
            return None
        cond_m = re.search(r"(?:点数|数|所得的数|取到的数|抽到的数|朝上的(?:一面)?(?:的)?点数|抽到|取到|摸到)\s*(?:是|为)?\s*((?:不)?(?:大于|小于|超过)\s*\d+|\d+\s*的倍数|偶数|奇数|质数|素数|合数|(?:是|为|等于)?\s*\d+)\s*(?:的(?:卡片|球|数))?\s*的概率", raw)
        if not cond_m:
            return None
        cond = cond_m.group(1)
        flags = [_cond_ok(x, cond) for x in range(lo, hi + 1)]
        if any(f is None for f in flags):
            return None
        good_n = [x for x, f in zip(range(lo, hi + 1), flags) if f]
        tot = hi - lo + 1
        p = F(len(good_n), tot)
        steps = [f"所有等可能的结果有 {tot} 种（{lo}~{hi}）",
                 f"满足“{cond}”的有 {len(good_n)} 种：" + ("、".join(map(str, good_n[:20])) if good_n else "没有"),
                 f"P = {len(good_n)}/{tot} = {fmt_num(p, max_dec=0)}"]
        return KernelSolution(kernel="prob.classical", answer=fmt_num(p, max_dec=0), steps=steps, hint=hint, explanation=expl,
                              answer_value=f"{p.numerator}/{p.denominator}" if p.denominator != 1 else str(p.numerator), answer_kind="num", check="枚举计数")
    # 2b) 转盘等分 n 份 / 卡片 1~n
    spin = re.search(r"(?:等分成|平均分成|分成)\s*(\d+|[一二三四五六七八九十]+)\s*(?:个|份)?.{0,12}?(?:扇形|区域|部分)", raw)
    if spin:
        n_ = int(spin.group(1)) if spin.group(1).isdigit() else (cn_small_number(spin.group(1)) or 0)
        if n_ <= 0:
            return None
        k_m = re.search(r"(?:停在|指向|落在).{0,6}?(?:红|黄|蓝|绿|白|黑)(?:色)?(?:区域|扇形)?", raw)
        if not k_m:
            return None
        p = F(1, n_)
        steps = [f"转盘被等分成 {n_} 份，指针停在每一份的可能性相同", f"P = 1/{n_}"]
        return KernelSolution(kernel="prob.classical", answer=fmt_num(p, max_dec=0), steps=steps, hint=hint, explanation=expl,
                              answer_value=f"1/{n_}", answer_kind="num", check="等可能计数")
    # 3) 抛两枚硬币
    if re.search(r"(?:抛|掷)\s*(?:两枚|2枚|两个)\s*(?:质地均匀的|均匀的)?\s*硬币|硬币\s*(?:抛|掷)?\s*两次|(?:抛|掷)(?:掷)?\s*一枚\s*(?:质地均匀的|均匀的)?\s*硬币\s*两次", raw):
        if re.search(r"都(?:是)?正面|两个正面|两枚都正面", raw):
            k, desc = 1, "两个都正面"
        elif re.search(r"都(?:是)?反面", raw):
            k, desc = 1, "两个都反面"
        elif re.search(r"一正一反|一个正面一个反面|一次正面一次反面", raw):
            k, desc = 2, "一正一反"
        elif re.search(r"至少一(?:个|枚|次)正面", raw):
            k, desc = 3, "至少一个正面"
        else:
            return None
        p = F(k, 4)
        steps = ["所有等可能结果：(正,正)、(正,反)、(反,正)、(反,反)，共 4 种", f"“{desc}”有 {k} 种，P = {k}/4 = {fmt_num(p, max_dec=0)}"]
        return KernelSolution(kernel="prob.two_step", answer=fmt_num(p, max_dec=0), steps=steps, hint=hint, explanation=expl,
                              answer_value=f"{p.numerator}/{p.denominator}", answer_kind="num", check="列表枚举")
    return None


# ── 比例 / 百分率 ────────────────────────────────────────────────────────────


def solve_ratio_percent(text: str) -> Optional[KernelSolution]:
    raw = basic_normalize(text)
    steps: list[str] = []
    # 按比分配
    m = re.search(r"(?:按|以)\s*(\d+)\s*[:：]\s*(\d+)(?:\s*[:：]\s*(\d+))?\s*(?:的比|分配|分给|分成)", raw)
    tot_m = re.search(r"(?:把|将)\s*(\d+(?:\.\d+)?)\s*(?:元|个|本|千克|kg|吨|米|人|棵|件|支|张|克|g)?", raw)
    tpl = _percent_templates(raw)
    if tpl is not None:
        return tpl
    if m and tot_m:
        parts = [int(x) for x in m.groups() if x]
        tot = F(tot_m.group(1))
        share = tot / sum(parts)
        vals = [share * p for p in parts]
        steps.append(f"总份数 = {' + '.join(map(str, parts))} = {sum(parts)}，每份 = {_fmt(tot)} ÷ {sum(parts)} = {_fmt(share)}")
        steps.append("各部分分别为 " + "、".join(f"{_fmt(share)}×{p} = {_fmt(v)}" for p, v in zip(parts, vals)))
        if sum(vals, F(0)) != tot:
            return None
        ask_max = re.search(r"最多|较多|多的|较大|最大|大的", raw)
        ask_min = re.search(r"最少|较少|少的|较小|最小|小的", raw)
        if ask_max or ask_min:
            v = max(vals) if ask_max else min(vals)
            return KernelSolution(kernel="ratio.allocate", answer=_fmt(v), steps=steps, hint="按比分配：先求总份数和每份是多少。",
                                  explanation="按比例分配。", answer_value=fmt_num(v, max_dec=8), answer_kind="num", check="各部分之和等于总数")
        return KernelSolution(kernel="ratio.allocate", answer="、".join(_fmt(v) for v in vals), steps=steps,
                              hint="按比分配：先求总份数和每份是多少。", explanation="按比例分配。",
                              answer_value=", ".join(fmt_num(v, max_dec=8) for v in vals), answer_kind="nums", check="各部分之和等于总数")
    # 连续两次（两年）平均增长/下降率
    m = re.search(r"(?:从|由)\s*(\d+(?:\.\d+)?)\s*(?:万元|元|万|亿元|吨|个|台|人|万人|kg)?\s*(?:增加|增长|提高|上升|下降|降低|减少|降)(?:到|至)\s*(\d+(?:\.\d+)?)", raw)
    if m and re.search(r"平均.{0,6}(?:增长率|下降率|降低率|降价率|百分率|增长的百分率)", raw) and re.search(r"两年|两次|2年|二年|两个月|两轮", raw):
        a, b = F(m.group(1)), F(m.group(2))
        up = b > a
        import sympy as sp

        x = sp.sqrt(sp.Rational(b.numerator * a.denominator, b.denominator * a.numerator))
        rate = (x - 1) if up else (1 - x)
        if not rate.is_Rational or rate <= 0:
            return None
        r = F(int(rate.p), int(rate.q))
        steps.append(f"设平均每次{'增长' if up else '下降'}率为 x，则 {_fmt(a)}(1 {'+' if up else '-'} x)² = {_fmt(b)}")
        steps.append(f"(1 {'+' if up else '-'} x)² = {_fmt(b / a)}，1 {'+' if up else '-'} x = {fmt_num(F(int(x.p), int(x.q)), max_dec=4)}（取正根，另一根不合题意舍去）")
        steps.append(f"x = {fmt_num(r * 100, max_dec=4)}%")
        if a * (1 + (r if up else -r)) ** 2 != b:
            return None
        return KernelSolution(kernel="ratio.growth_rate", answer=f"{fmt_num(r * 100, max_dec=4)}%", steps=steps,
                              hint="增长率问题：a(1±x)² = b，开平方后注意舍去不合题意的根。",
                              explanation="一元二次方程的应用（增长率）。", answer_value=fmt_num(r * 100, max_dec=6), answer_kind="num", unit="%", check="代回 a(1±x)²=b")
    # 原价 / 现价 → 降价（涨价）百分之几
    m = re.search(r"原(?:价|来)(?:是|为)?\s*(\d+(?:\.\d+)?)\s*(?:元|万元|吨|个|人|千克|kg)?.{0,12}?(?:现(?:价|在)|后来|今年)(?:是|为)?\s*(\d+(?:\.\d+)?)", raw)
    if m and re.search(r"百分之几|百分率|降价率|增长率|提高了百分|降低了百分|增加了百分|减少了百分|几成", raw):
        a, b = F(m.group(1)), F(m.group(2))
        if a == 0 or a == b:
            return None
        r = abs(b - a) / a
        word = "降低" if b < a else "提高"
        steps.append(f"变化量 = |{_fmt(b)} - {_fmt(a)}| = {_fmt(abs(b - a))}")
        steps.append(f"{word}的百分率 = 变化量 ÷ 原来的量 = {_fmt(abs(b - a))} ÷ {_fmt(a)} = {fmt_num(r * 100, max_dec=4)}%")
        return KernelSolution(kernel="ratio.percent_change", answer=f"{word}了 {fmt_num(r * 100, max_dec=4)}%", steps=steps,
                              hint="变化的百分率 = 变化量 ÷ 原来的量（单位“1”是原来的量）。",
                              explanation="百分率的计算。", answer_value=fmt_num(r * 100, max_dec=6), answer_kind="num", unit="%", check="原量×(1±r)=现量")
    # 比现在多/少 x% → 求原来或现在
    m = re.search(r"比原(?:来|计划|价)?(?:增加|提高|增长|多)了?\s*(\d+(?:\.\d+)?)\s*%.{0,12}?(?:现在|实际|现价)(?:是|为)?\s*(\d+(?:\.\d+)?)", raw)
    if m and re.search(r"原(?:来|计划|价).{0,6}(?:多少|几)", raw):
        r, now = F(m.group(1)) / 100, F(m.group(2))
        orig = now / (1 + r)
        steps.append(f"把原来的量看作单位“1”，现在是原来的 (1 + {fmt_num(r * 100)}%)")
        steps.append(f"原来 = {_fmt(now)} ÷ (1 + {fmt_num(r * 100)}%) = {_fmt(orig)}")
        return KernelSolution(kernel="ratio.percent_base", answer=_fmt(orig), steps=steps, hint="已知比单位“1”多百分之几的量，求单位“1”用除法。",
                              explanation="百分数应用题。", answer_value=fmt_num(orig, max_dec=8), answer_kind="num", check="原来×(1+r)=现在")
    # 比例式 a:b = c:x
    m = re.search(r"(\d+(?:\.\d+)?)\s*[:：]\s*(\d+(?:\.\d+)?)\s*=\s*(\d+(?:\.\d+)?|x)\s*[:：]\s*(\d+(?:\.\d+)?|x)", raw)
    if m and list(m.groups()).count("x") == 1 and re.search(r"解比例|求\s*x|x\s*=", raw):
        g = list(m.groups())
        idx = g.index("x")
        a, b, c, d = (F(v) if v != "x" else F(0) for v in g)
        if idx == 3:
            res = b * c / a
        elif idx == 2:
            res = a * d / b
        elif idx == 1:
            res = a * d / c
        else:
            res = b * c / d
        steps.append("比例的基本性质：两内项之积等于两外项之积")
        steps.append(f"x = {_fmt(res)}")
        return KernelSolution(kernel="ratio.proportion", answer=f"x = {_fmt(res)}", steps=steps, hint="内项之积 = 外项之积。",
                              explanation="解比例。", answer_value=fmt_num(res, max_dec=8), answer_kind="num", check="内项积=外项积")
    return None


_UP = r"涨价|提价|上涨|增加|增长|提高|多"
_DOWN = r"降价|降低|下降|减少|下跌|少"


def _percent_templates(raw: str) -> Optional[KernelSolution]:
    """百分数应用：占百分之几、连续涨降、A 比 B 多/少 p%。"""
    hint = "百分数应用题：先找单位“1”（谁的百分之几），比单位“1”多 p% 就是 ×(1+p%)，少 p% 就是 ×(1-p%)。"
    steps: list[str] = []
    # 1) 部分占整体的百分数
    m = re.search(r"(?:共有|有|共)\s*(\d+(?:\.\d+)?)\s*(?:名|个|人|本|棵|只|件)?.{0,12}?其中\s*(\d+(?:\.\d+)?)", raw)
    if m and re.search(r"占.{0,10}(?:百分数|百分之几|百分比|百分率)", raw):
        tot, part = F(m.group(1)), F(m.group(2))
        if tot == 0 or part > tot:
            return None
        r = part / tot * 100
        steps.append(f"所占百分数 = 部分 ÷ 整体 × 100% = {_fmt(part)} ÷ {_fmt(tot)} × 100% = {_fmt(r)}%")
        return KernelSolution(kernel="ratio.percent_of", answer=f"{_fmt(r)}%", steps=steps, hint=hint, explanation="求一个数占另一个数的百分之几。",
                              answer_value=fmt_num(r, max_dec=6), answer_kind="num", unit="%", check="部分=整体×百分数")
    # 2) 连续变化：先涨 a% 再降 b%
    changes = list(re.finditer(rf"(?:先|再|又|然后)\s*({_UP}|{_DOWN})(?:了)?\s*(\d+(?:\.\d+)?)\s*%", raw))
    if len(changes) >= 2:
        k = F(1)
        parts = []
        for c in changes:
            p = F(c.group(2)) / 100
            up = re.fullmatch(_UP, c.group(1)) is not None
            k *= (1 + p) if up else (1 - p)
            parts.append(f"(1 {'+' if up else '-'} {_fmt(p * 100)}%)")
        steps.append("现价 = 原价 × " + " × ".join(parts) + f" = 原价 × {_fmt(k)}")
        orig = re.search(r"原价(?:是|为)?\s*(\d+(?:\.\d+)?)\s*元", raw)
        if re.search(r"原价的百分之几|是原价的", raw):
            steps.append(f"现价是原价的 {_fmt(k * 100)}%")
            return KernelSolution(kernel="ratio.successive_change", answer=f"{_fmt(k * 100)}%", steps=steps, hint=hint,
                                  explanation="连续两次百分数变化（单位“1”不同）。", answer_value=fmt_num(k * 100, max_dec=6), answer_kind="num", unit="%", check="逐次相乘")
        if orig:
            o = F(orig.group(1))
            now = o * k
            steps.append(f"现价 = {_fmt(o)} × {_fmt(k)} = {_fmt(now)} 元")
            if re.search(r"(?:比原价)?(?:少|便宜|降低)了?多少元|少多少元", raw):
                steps.append(f"比原价少 {_fmt(o - now)} 元")
                return KernelSolution(kernel="ratio.successive_change", answer=f"{_fmt(o - now)} 元", steps=steps, hint=hint,
                                      explanation="连续两次百分数变化。", answer_value=fmt_num(o - now, max_dec=6), answer_kind="num", unit="元", check="逐次相乘")
            if re.search(r"(?:比原价)?(?:多|贵|提高)了?多少元", raw):
                return KernelSolution(kernel="ratio.successive_change", answer=f"{_fmt(now - o)} 元", steps=steps, hint=hint,
                                      explanation="连续两次百分数变化。", answer_value=fmt_num(now - o, max_dec=6), answer_kind="num", unit="元", check="逐次相乘")
            if re.search(r"现价(?:是)?多少", raw):
                return KernelSolution(kernel="ratio.successive_change", answer=f"{_fmt(now)} 元", steps=steps, hint=hint,
                                      explanation="连续两次百分数变化。", answer_value=fmt_num(now, max_dec=6), answer_kind="num", unit="元", check="逐次相乘")
        return None
    # 3) A 比 B 多/少 p%，已知 B 求 A（或已知 A 求 B）
    m = re.search(rf"([\u4e00-\u9fff]{{1,3}}?)(?:的[\u4e00-\u9fff]{{0,4}})?比([\u4e00-\u9fff]{{1,3}}?)(?:的[\u4e00-\u9fff]{{0,4}})?({_UP}|{_DOWN})(?:了)?\s*(\d+(?:\.\d+)?)\s*%", raw)
    if m:
        A, Bn, word, pct = m.group(1), m.group(2), m.group(3), F(m.group(4)) / 100
        up = re.fullmatch(_UP, word) is not None
        k = (1 + pct) if up else (1 - pct)
        vb = re.search(rf"{Bn}[\u4e00-\u9fff]{{0,8}}?(?:为|是|有)?\s*(\d+(?:\.\d+)?)\s*(元|吨|千克|kg|人|个|万元|本|台|件|米|只|棵)?", raw[: m.start()] + "，" + raw[m.end():])
        ask_a = re.search(rf"{A}[\u4e00-\u9fff]{{0,8}}?(?:是|为|有)?多少", raw[m.end():])
        if vb and ask_a and A != Bn:
            b = F(vb.group(1))
            a = b * k
            u = vb.group(2) or ""
            steps.append(f"把{Bn}看作单位“1”，{A}是{Bn}的 (1 {'+' if up else '-'} {_fmt(pct * 100)}%)")
            steps.append(f"{A} = {_fmt(b)} × {_fmt(k)} = {_fmt(a)}{(' ' + u) if u else ''}")
            return KernelSolution(kernel="ratio.percent_base", answer=f"{_fmt(a)}{(' ' + u) if u else ''}", steps=steps, hint=hint,
                                  explanation="百分数应用（已知单位“1”求比较量）。", answer_value=fmt_num(a, max_dec=6), answer_kind="num", unit=u,
                                  check="比较量÷单位1=1±p%")
    return None


# ── 单位换算 ─────────────────────────────────────────────────────────────────

_LEN = {"千米": F(1000), "km": F(1000), "公里": F(1000), "米": F(1), "m": F(1), "分米": F(1, 10), "dm": F(1, 10),
        "厘米": F(1, 100), "cm": F(1, 100), "毫米": F(1, 1000), "mm": F(1, 1000), "微米": F(1, 10**6), "μm": F(1, 10**6), "纳米": F(1, 10**9), "nm": F(1, 10**9)}
_MASS = {"吨": F(1000), "t": F(1000), "千克": F(1), "kg": F(1), "公斤": F(1), "克": F(1, 1000), "g": F(1, 1000), "毫克": F(1, 10**6), "mg": F(1, 10**6)}
_TIME = {"小时": F(3600), "时": F(3600), "h": F(3600), "分钟": F(60), "分": F(60), "min": F(60), "秒": F(1), "s": F(1), "天": F(86400)}
_AREA = {"平方千米": F(10**6), "km²": F(10**6), "km^2": F(10**6), "公顷": F(10**4), "平方米": F(1), "m²": F(1), "m^2": F(1),
         "平方分米": F(1, 100), "dm²": F(1, 100), "dm^2": F(1, 100), "平方厘米": F(1, 10**4), "cm²": F(1, 10**4), "cm^2": F(1, 10**4),
         "平方毫米": F(1, 10**6), "mm²": F(1, 10**6), "mm^2": F(1, 10**6)}
_VOL = {"立方米": F(1), "m³": F(1), "m^3": F(1), "立方分米": F(1, 1000), "dm³": F(1, 1000), "dm^3": F(1, 1000), "升": F(1, 1000), "L": F(1, 1000),
        "立方厘米": F(1, 10**6), "cm³": F(1, 10**6), "cm^3": F(1, 10**6), "毫升": F(1, 10**6), "mL": F(1, 10**6), "ml": F(1, 10**6)}
_SPEED = {"km/h": F(1000, 3600), "千米/时": F(1000, 3600), "千米每小时": F(1000, 3600), "m/s": F(1), "米/秒": F(1), "米每秒": F(1)}
_DENS = {"g/cm³": F(1000), "g/cm^3": F(1000), "克/立方厘米": F(1000), "kg/m³": F(1), "kg/m^3": F(1), "千克/立方米": F(1)}
_TABLES = [_SPEED, _DENS, _AREA, _VOL, _LEN, _MASS, _TIME]


def _unit_pat(table: dict[str, Fraction]) -> str:
    keys = sorted(table, key=len, reverse=True)
    return "|".join(re.escape(k) for k in keys)


_CN_ASK = re.compile(r"(?:等于|是|合|换算成|化成)(?:多少|几)(?:个)?")


def solve_unit_conversion(text: str) -> Optional[KernelSolution]:
    raw = basic_normalize(text).replace(" ", "")
    raw = _CN_ASK.sub("=", raw).rstrip("?？。.")
    for table in _TABLES:
        up = _unit_pat(table)
        # 复合：2小时15分 = ? 分
        m = re.search(rf"((?:\d+(?:\.\d+)?(?:{up}))+)\s*=\s*(?:\(\s*\)|\?|_+|多少|（\s*）)?\s*({up})(?![a-zA-Z²³^/])", raw)
        if not m:
            continue
        lhs = m.group(1)
        pieces = re.findall(rf"(\d+(?:\.\d+)?)({up})", lhs)
        if not pieces or "".join(a + b for a, b in pieces) != lhs:
            continue
        target = m.group(2)
        si = sum((F(a) * table[b] for a, b in pieces), F(0))
        res = si / table[target]
        steps = []
        for a, b in pieces:
            steps.append(f"{a}{b} = {fmt_num(F(a) * table[b] / table[target], max_dec=8)}{target}（1{b} = {fmt_num(table[b] / table[target], max_dec=8)}{target}）")
        if len(pieces) > 1:
            steps.append(f"合计 = {fmt_num(res, max_dec=8)}{target}")
        if res * table[target] != si:
            return None
        return KernelSolution(kernel="unit.convert", answer=f"{fmt_num(res, max_dec=8)}{target}", steps=steps,
                              hint="大单位化小单位乘进率，小单位化大单位除以进率；面积、体积的进率要平方、立方。",
                              explanation="单位换算。", answer_value=fmt_num(res, max_dec=10), answer_kind="num", unit=target, check="反向换算还原")
    return None


__all__ = ["solve_probability", "solve_ratio_percent", "solve_statistics", "solve_unit_conversion"]
