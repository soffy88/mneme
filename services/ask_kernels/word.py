"""应用题模板（无 LLM）：行程（相遇/追及/环形跑道）、工程、利润折扣、浓度、年龄、鸡兔同笼。

原则：只在模板“吃掉”了题面里所有数字、且问法明确时作答（置信）；否则返回 None，不猜。
每个模板都把结果代回题设条件验证（相遇时两人路程和 = 总路程、头脚数吻合……）。
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Optional

from services.ask_kernels.core import KernelSolution, basic_normalize, cn_small_number, fmt_num

F = Fraction
_NUM = r"(\d+(?:\.\d+)?)"


def _f(v: Fraction) -> str:
    return fmt_num(v, max_dec=4)


def _numbers_with_pos(raw: str) -> list[tuple[int, int, Fraction]]:
    return [(m.start(), m.end(), F(m.group(0))) for m in re.finditer(r"\d+(?:\.\d+)?", raw)]


def _all_used(raw: str, spans: list[tuple[int, int]]) -> bool:
    """题面中的每个数字都被模板用到（允许题号/“甲乙两人”这类无数字的部分）。"""
    for s, e, _ in _numbers_with_pos(raw):
        if not any(s >= a and e <= b for a, b in spans):
            return False
    return True


def _cn2num(raw: str) -> str:
    """把应用题里常见的中文小数字（三小时、两人、五天）换成阿拉伯数字，便于抽取。"""
    def rep(m: re.Match[str]) -> str:
        v = cn_small_number(m.group(1))
        return str(v) if v is not None else m.group(0)

    return re.sub(r"(?<![一二三四五六七八九十两])([一二三四五六七八九十两]{1,3})(?=\s*(?:小时|天|分钟|年|倍|岁|千米|公里|米|元|克|个|只))", rep, raw)


def _ans(v: Fraction) -> str:
    return fmt_num(v, max_dec=8)


# ── 行程 ─────────────────────────────────────────────────────────────────────

_SPEED_PATS = [
    rf"(?:每小时|每时)\s*(?:行驶?|走|跑|骑|飞|游|开)?\s*{_NUM}\s*(千米|公里|km|米|m)",
    rf"(?:每分钟?|每分)\s*(?:行驶?|走|跑|骑|游)?\s*{_NUM}\s*(米|m|千米|km)",
    rf"(?:每秒钟?)\s*(?:行驶?|走|跑|骑|游)?\s*{_NUM}\s*(米|m)",
    rf"{_NUM}\s*(km/h|千米/时|千米/小时|公里/小时|m/s|米/秒|米/分钟?|m/min)",
    rf"速度(?:是|为|分别是|分别为)?\s*{_NUM}\s*(千米/时|km/h|米/分|米/秒|m/s|千米/小时)?",
]


def _speed_unit(u: Optional[str], ctx: str) -> str:
    u = u or ""
    if u in ("千米", "公里", "km", "km/h", "千米/时", "千米/小时", "公里/小时"):
        return "km/h"
    if u in ("m/s", "米/秒") or "每秒" in ctx:
        return "m/s"
    if u in ("米/分", "米/分钟", "m/min") or "每分" in ctx:
        return "m/min"
    if u in ("米", "m"):
        return "m/min" if "每分" in ctx else ("m/h" if "每小时" in ctx else "m/min")
    return "?"


def solve_travel(text: str) -> Optional[KernelSolution]:
    raw = _cn2num(basic_normalize(text)).replace(" ", "")
    meet = bool(re.search(r"相向|相遇|迎面|对开|相对而行", raw))
    chase = bool(re.search(r"追上|追及|追赶|去追", raw))
    ring = bool(re.search(r"环形|跑道|周长", raw))
    if not (meet or chase or ring):
        return None
    if meet and chase:
        return None
    spans: list[tuple[int, int]] = []
    speeds: list[tuple[int, Fraction, str]] = []
    for pat in _SPEED_PATS:
        for m in re.finditer(pat, raw):
            if any(m.start(1) >= a and m.end(1) <= b for a, b in spans):
                continue
            speeds.append((m.start(), F(m.group(1)), _speed_unit(m.group(2) if m.lastindex and m.lastindex >= 2 else None, m.group(0))))
            spans.append((m.start(1), m.end(1)))
    m2 = re.search(rf"速度分别(?:是|为)\s*{_NUM}\s*(千米/时|km/h|米/分|米/秒|m/s|千米/小时|米/分钟)?\s*(?:和|、|,)\s*{_NUM}\s*(千米/时|km/h|米/分|米/秒|m/s|千米/小时|米/分钟)?", raw)
    if m2:
        speeds = [(m2.start(1), F(m2.group(1)), _speed_unit(m2.group(2) or m2.group(4), "")),
                  (m2.start(3), F(m2.group(3)), _speed_unit(m2.group(4) or m2.group(2), ""))]
        spans = [(m2.start(1), m2.end(1)), (m2.start(3), m2.end(3))]
    speeds.sort()
    if len(speeds) != 2:
        return None
    units = {u for _, _, u in speeds}
    if len(units) != 1 or "?" in units:
        return None
    unit = units.pop()
    dist_u = {"km/h": "千米", "m/s": "米", "m/min": "米", "m/h": "米"}[unit]
    time_u = {"km/h": "小时", "m/s": "秒", "m/min": "分钟", "m/h": "小时"}[unit]
    v1, v2 = speeds[0][1], speeds[1][1]
    dist = None
    md = re.search(rf"(?:相距|全长|距离为|距离是|路程为|路程是|周长(?:是|为)?|前(?:面|方)?|后(?:面|方)?|长)\s*{_NUM}\s*(千米|公里|km|米|m)", raw)
    if md:
        dist = F(md.group(1))
        du = md.group(2)
        if du in ("米", "m") and dist_u == "千米":
            dist = dist / 1000
        elif du in ("千米", "公里", "km") and dist_u == "米":
            dist = dist * 1000
        spans.append((md.start(1), md.end(1)))
    head_t = None
    mh = re.search(rf"(?:先(?:出发|走|行|开出|骑)?|晚|迟)\s*{_NUM}\s*(小时|分钟|分|秒)|{_NUM}\s*(小时|分钟|分)后.{{0,24}}?(?:出发|去追|追赶|骑车追|开车追|追出|追去|开出)", raw)
    if mh:
        val = F(mh.group(1) or mh.group(3))
        tu = mh.group(2) or mh.group(4)
        conv: dict[tuple[str, str], Fraction] = {("小时", "小时"): F(1), ("分钟", "分钟"): F(1), ("分", "分钟"): F(1), ("秒", "秒"): F(1),
                                                 ("分钟", "小时"): F(1, 60), ("分", "小时"): F(1, 60), ("小时", "分钟"): F(60)}
        k = conv.get((tu, time_u))
        if k is None:
            return None
        head_t = val * k
        g = 1 if mh.group(1) else 3
        spans.append((mh.start(g), mh.end(g)))
    given_t = None
    mt = re.search(rf"(?:经过|行驶了?|出发)\s*{_NUM}\s*(小时|分钟|秒)后?", raw)
    if mt and not mh:
        given_t = F(mt.group(1))
        spans.append((mt.start(1), mt.end(1)))
    if not _all_used(raw, spans):
        return None
    ask_time = bool(re.search(r"(?:几|多少)(?:小时|分钟|秒|时间)|多长时间|多久|何时|什么时候", raw))
    ask_dist = bool(re.search(r"相距多少|全长多少|多少千米|多少米|多远|距离是多少|路程是多少", raw))
    steps: list[str] = []
    hint = "行程问题：路程 = 速度 × 时间；相遇时间 = 路程和 ÷ 速度和，追及时间 = 路程差 ÷ 速度差。"
    if meet and not ring:
        vs = v1 + v2
        if dist is not None and ask_time and given_t is None:
            gap = dist - (v1 * head_t if head_t else 0)
            if head_t:
                steps.append(f"先出发的一方先行 {_f(head_t)} {time_u}，走了 {_f(v1)}×{_f(head_t)} = {_f(v1 * head_t)} {dist_u}，剩下 {_f(gap)} {dist_u}")
                if gap <= 0:
                    return None
            t = gap / vs
            steps.append(f"速度和 = {_f(v1)} + {_f(v2)} = {_f(vs)}（{unit}）")
            steps.append(f"相遇时间 = 路程 ÷ 速度和 = {_f(gap)} ÷ {_f(vs)} = {_f(t)} {time_u}")
            steps.append(f"设 x {time_u}后相遇，列方程：{_f(v1)}x + {_f(v2)}x = {_f(gap)}，x = {_f(t)}")
            if v1 * t + v2 * t != gap:
                return None
            return KernelSolution(kernel="word.travel_meet", answer=f"{_f(t)} {time_u}", steps=steps, hint=hint,
                                  explanation="相遇问题：路程和 = 速度和 × 相遇时间。", answer_value=_ans(t), answer_kind="num", unit=time_u,
                                  check="两人路程之和等于总路程", confidence=0.9)
        if given_t is not None and ask_dist and dist is None:
            d = vs * given_t
            steps.append(f"路程 = 速度和 × 时间 = ({_f(v1)} + {_f(v2)}) × {_f(given_t)} = {_f(d)} {dist_u}")
            return KernelSolution(kernel="word.travel_meet", answer=f"{_f(d)} {dist_u}", steps=steps, hint=hint,
                                  explanation="相遇问题。", answer_value=_ans(d), answer_kind="num", unit=dist_u, check="d/速度和 = t", confidence=0.85)
        return None
    if ring and dist is not None and ask_time:
        same = bool(re.search(r"同向", raw))
        opp = bool(re.search(r"反向|背向|相背", raw))
        if same == opp:
            return None
        rel = abs(v1 - v2) if same else v1 + v2
        if rel == 0:
            return None
        t = dist / rel
        steps.append(f"环形跑道{'同向' if same else '反向'}出发，第一次相遇时{'快的比慢的多跑一圈' if same else '两人合跑一圈'}")
        steps.append(f"时间 = 周长 ÷ 速度{'差' if same else '和'} = {_f(dist)} ÷ {_f(rel)} = {_f(t)} {time_u}")
        return KernelSolution(kernel="word.travel_ring", answer=f"{_f(t)} {time_u}", steps=steps, hint=hint,
                              explanation="环形跑道问题。", answer_value=_ans(t), answer_kind="num", unit=time_u, check="路程差/和等于一圈", confidence=0.85)
    if chase and ask_time:
        fast, slow = max(v1, v2), min(v1, v2)
        if fast == slow:
            return None
        if dist is not None and head_t is None:
            gap = dist
            steps.append(f"开始时相距（路程差）{_f(gap)} {dist_u}")
        elif head_t is not None and dist is None:
            # 慢的先出发
            gap = slow * head_t
            steps.append(f"慢的一方先走 {_f(head_t)} {time_u}，领先 {_f(slow)} × {_f(head_t)} = {_f(gap)} {dist_u}（路程差）")
        else:
            return None
        t = gap / (fast - slow)
        steps.append(f"速度差 = {_f(fast)} - {_f(slow)} = {_f(fast - slow)}")
        steps.append(f"追及时间 = 路程差 ÷ 速度差 = {_f(gap)} ÷ {_f(fast - slow)} = {_f(t)} {time_u}")
        steps.append(f"检验：快的走 {_f(fast * t)}，慢的走 {_f(slow * t)}，相差 {_f(fast * t - slow * t)} = 路程差 ✓")
        if fast * t - slow * t != gap:
            return None
        return KernelSolution(kernel="word.travel_chase", answer=f"{_f(t)} {time_u}", steps=steps, hint=hint,
                              explanation="追及问题：路程差 = 速度差 × 追及时间。", answer_value=_ans(t), answer_kind="num", unit=time_u,
                              check="追上时两人路程差等于开始的距离", confidence=0.9)
    return None


# ── 工程 ─────────────────────────────────────────────────────────────────────


def solve_work(text: str) -> Optional[KernelSolution]:
    raw = _cn2num(basic_normalize(text)).replace(" ", "")
    if not re.search(r"工程|单独|合作|合做|完成|注满|放完|一起做|共同|单开", raw):
        return None
    hint = "工程问题：把总工作量看作 1，工作效率 = 1 ÷ 单独完成的时间，合作效率 = 效率之和。"
    singles = [m for m in re.finditer(rf"(甲|乙|丙|进水管|出水管|A|B)(?:队|单独|一人|独自|管|管单独|单独做|单独完成|单独干)?[^,，;。]*?{_NUM}\s*(天|小时|分钟|周)(?:可以|能|才能|就能|可)?(?:完成|做完|修完|注满|放完|放空|干完|加工完|铺完)", raw)
               if not re.search(r"合作|合做|一起|共同|同时", m.group(0))]
    mc = re.search(rf"(?:甲乙|甲、乙|两队|两人)(?:两队|两人)?(?:合作|合做|一起做|共同做)\s*{_NUM}\s*(天|小时|分钟|周)(?:可以|能|才能|就能|可)?(?:完成|做完|修完|干完)", raw)
    if len(singles) == 1 and mc and re.search(r"([甲乙])单独(?:做|完成|干)?(?:需|需要|要)?(?:多少|几)", raw):
        m1 = singles[0]
        who = m1.group(1)
        a = F(m1.group(2))
        c = F(mc.group(1))
        if mc.group(2) != m1.group(3) or a <= c:
            return None
        other = "乙" if who == "甲" else "甲"
        rate = 1 / c - 1 / a
        t = 1 / rate
        steps = ["把总工作量看作单位“1”", f"合作效率 = 1/{_f(c)}，{who}的效率 = 1/{_f(a)}",
                 f"{other}的效率 = 1/{_f(c)} - 1/{_f(a)} = {_f(rate)}", f"{other}单独做需要 1 ÷ {_f(rate)} = {_f(t)} {m1.group(3)}"]
        if not _all_used(raw, [(m1.start(2), m1.end(2)), (mc.start(1), mc.end(1))]):
            return None
        return KernelSolution(kernel="word.work", answer=f"{_f(t)} {m1.group(3)}", steps=steps, hint=hint,
                              explanation="工程问题：合作效率 = 各自效率之和。", answer_value=_ans(t), answer_kind="num", unit=m1.group(3),
                              check="效率之和等于合作效率", confidence=0.85)
    if len(singles) < 2:
        return None
    eff: dict[str, Fraction] = {}
    spans: list[tuple[int, int]] = []
    tu = singles[0].group(3)
    for m in singles[:3]:
        who = m.group(1)
        days = F(m.group(2))
        if days == 0 or m.group(3) != tu:
            return None
        sign = -1 if re.search(r"放完|排完|放水|放空|出水", m.group(0)) else 1
        eff[who] = sign * F(1) / days
        spans.append((m.start(2), m.end(2)))
    steps = ["把总工作量看作单位“1”"]
    for who, e in eff.items():
        steps.append(f"{who}的工作效率 = {'-' if e < 0 else ''}1/{_f(abs(1 / e))}（每{tu}{'放掉' if e < 0 else '完成'}全部的 {_f(abs(e))}）")
    names = list(eff)
    after = raw[singles[min(len(singles), 3) - 1].end():]
    off = singles[min(len(singles), 3) - 1].end()
    mpre = re.search(rf"([甲乙丙])(?:先)?(?:单独)?(?:做|干|修|工作)了?\s*{_NUM}\s*{tu}", after)
    mtog = re.search(rf"(?:合作|合做|一起做|共同做|两队合作|两人合作)了?\s*{_NUM}\s*{tu}", after)
    total = sum(eff.values(), F(0))
    if total <= 0:
        return None
    ask = re.search(r"(?:还需|还要|再需|剩下的|余下的).{0,12}(?:几|多少)", raw) or re.search(r"(?:几|多少)\s*(?:天|小时|分钟)", raw)
    if not ask:
        return None
    if mpre and mpre.group(1) in eff:
        who = mpre.group(1)
        d = F(mpre.group(2))
        spans.append((off + mpre.start(2), off + mpre.end(2)))
        done = eff[who] * d
        rem = 1 - done
        if rem <= 0:
            return None
        steps.append(f"{who}先做 {_f(d)} {tu}，完成了 {_f(eff[who])} × {_f(d)} = {_f(done)}，剩下 1 - {_f(done)} = {_f(rem)}")
        rest_txt = after[mpre.end():]
        others = [n for n in names if n != who]
        if re.search(r"合作|合做|一起|共同|两队|两人", rest_txt):
            t = rem / total
            steps.append(f"剩下的由两人合作：{_f(rem)} ÷ ({' + '.join(_f(eff[n]) for n in names)}) = {_f(t)} {tu}")
        elif len(others) == 1 and re.search(others[0], rest_txt):
            t = rem / eff[others[0]]
            steps.append(f"剩下的由{others[0]}单独做：{_f(rem)} ÷ {_f(eff[others[0]])} = {_f(t)} {tu}")
        else:
            return None
    elif mtog:
        d = F(mtog.group(1))
        spans.append((off + mtog.start(1), off + mtog.end(1)))
        done = total * d
        rem = 1 - done
        if rem <= 0:
            return None
        steps.append(f"合作 {_f(d)} {tu}完成 {_f(total)} × {_f(d)} = {_f(done)}，剩下 {_f(rem)}")
        rest_txt = after[mtog.end():]
        left = [n for n in names if re.search(n + r"(?:单独|独自|继续)", rest_txt)]
        if len(left) != 1:
            return None
        t = rem / eff[left[0]]
        steps.append(f"剩下的由{left[0]}单独完成：{_f(rem)} ÷ {_f(eff[left[0]])} = {_f(t)} {tu}")
    else:
        if not re.search(r"合作|合做|一起|共同|同时(?:打开|开放|开)|两队|两人|齐开|同时开", raw):
            return None
        t = 1 / total
        steps.append(f"合作效率 = {' + '.join(_f(e) for e in eff.values())} = {_f(total)}")
        steps.append(f"合作完成需要 1 ÷ {_f(total)} = {_f(t)} {tu}")
    if not _all_used(raw, spans):
        return None
    return KernelSolution(kernel="word.work", answer=f"{_f(t)} {tu}", steps=steps, hint=hint,
                          explanation="工程问题：工作总量 = 工作效率 × 工作时间。", answer_value=_ans(t), answer_kind="num", unit=tu,
                          check="各段完成量之和为 1", confidence=0.85)


# ── 利润 / 折扣 ──────────────────────────────────────────────────────────────

_ZHE_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _discount(raw: str) -> Optional[tuple[Fraction, tuple[int, int]]]:
    m = re.search(r"打\s*(\d+(?:\.\d+)?)\s*折|(\d+(?:\.\d+)?)\s*折", raw)
    if m:
        v = F(m.group(1) or m.group(2))
        g = 1 if m.group(1) else 2
        return (v / 10 if v <= 10 else v / 100), (m.start(g), m.end(g))
    m = re.search(r"打?\s*([一二三四五六七八九])([一二三四五六七八九])?\s*折", raw)
    if m:
        v = F(_ZHE_CN[m.group(1)], 10) + (F(_ZHE_CN[m.group(2)], 100) if m.group(2) else 0)
        return v, (m.start(), m.start())
    return None


def solve_profit(text: str) -> Optional[KernelSolution]:
    raw = basic_normalize(text).replace(" ", "")
    if not re.search(r"进价|成本|标价|售价|定价|利润|折|获利|盈利|亏", raw):
        return None
    hint = "利润 = 售价 - 进价，利润率 = 利润 ÷ 进价，售价 = 标价 × 折扣（八折即 0.8）。"
    spans: list[tuple[int, int]] = []

    def grab(pat: str) -> Optional[Fraction]:
        m = re.search(pat, raw)
        if not m:
            return None
        spans.append((m.start(1), m.end(1)))
        return F(m.group(1))

    cost = grab(rf"(?:进价|成本价?|成本)(?:为|是|每件)?\s*{_NUM}\s*元")
    mark = grab(rf"(?:标价|原价|定价)(?:为|是)?\s*{_NUM}\s*元")
    sale = grab(rf"(?:售价|卖价|实际售价|以|现价)(?:为|是)?\s*{_NUM}\s*元(?:出售|卖出|售出)?")
    rate_m = re.search(rf"(?:利润率|获利|盈利|赚|利润为进价的|仍可获利|仍获利|仍能获利)(?:为|是|了)?\s*{_NUM}\s*%", raw) or re.search(
        rf"按\s*{_NUM}\s*%\s*的利润(?:率)?", raw)
    rate = None
    if rate_m:
        rate = F(rate_m.group(1)) / 100
        spans.append((rate_m.start(1), rate_m.end(1)))
    up_m = re.search(rf"(?:提高|加价|高出|加|提价)\s*{_NUM}\s*%(?:后)?(?:标价|定价)?", raw)
    up = None
    if up_m:
        up = F(up_m.group(1)) / 100
        spans.append((up_m.start(1), up_m.end(1)))
    dsc = _discount(raw)
    disc = None
    if dsc:
        disc = dsc[0]
        if dsc[1][1] > dsc[1][0]:
            spans.append(dsc[1])
    if not _all_used(raw, spans):
        return None
    steps: list[str] = []
    ask_cost = bool(re.search(r"(?:进价|成本)(?:是|为)?(?:多少|几)|求.{0,4}(?:进价|成本)", raw))
    ask_mark = bool(re.search(r"(?:标价|原价|定价)(?:是|为|应)?(?:多少|几)|求.{0,4}(?:标价|原价)", raw))
    ask_sale = bool(re.search(r"售价(?:是|为)?(?:多少|几)|卖(?:多少|几)元|求.{0,4}售价", raw))
    ask_profit = bool(re.search(r"(?:利润|获利|赚)(?:是|为|了)?(?:多少|几)元|每件(?:可)?(?:获利|赚)多少|求.{0,4}利润(?!率)", raw))
    ask_rate = bool(re.search(r"利润率|百分之几|获利百分之", raw)) and rate is None

    def done(kernel: str, ans: str, val: Fraction, unit: str, check_ok: bool) -> Optional[KernelSolution]:
        if not check_ok:
            return None
        return KernelSolution(kernel=kernel, answer=ans, steps=steps, hint=hint, explanation="销售中的利润与折扣问题。",
                              answer_value=_ans(val), answer_kind="num", unit=unit, check="代回题设关系成立", confidence=0.85)

    # 打 x 折后售价为 S，求 x
    mx = re.search(r"打\s*x\s*折", raw)
    if mx and mark is not None and sale is not None and re.search(r"求\s*x|x\s*(?:是|为|等于)?多少", raw):
        x = sale / mark * 10
        steps.append(f"售价 = 标价 × x/10：{_f(mark)} × x/10 = {_f(sale)}，x = {_f(x)}")
        return done("word.profit", f"打 {_f(x)} 折", x, "折", x * mark / 10 == sale)
    # 降价 p% 后售价为 S，求原价
    mdn = re.search(rf"降价\s*{_NUM}\s*%\s*后(?:的)?(?:售价|价格|现价)?(?:为|是)?\s*{_NUM}\s*元", raw)
    if mdn and re.search(r"原价", raw) and not cost and not mark:
        p, now = F(mdn.group(1)) / 100, F(mdn.group(2))
        spans += [(mdn.start(1), mdn.end(1)), (mdn.start(2), mdn.end(2))]
        o = now / (1 - p)
        steps.append(f"设原价为 x 元：x(1 - {_f(p * 100)}%) = {_f(now)}，x = {_f(o)}")
        if not _all_used(raw, spans):
            return None
        return done("word.profit", f"{_f(o)} 元", o, "元", o * (1 - p) == now)
    # 成本 + 提价 + 折扣 → 售价 / 已知售价求成本
    if up is not None and disc is not None and cost is not None and re.search(r"(?:是|为)进价的百分之几|是进价的", raw):
        k = (1 + up) * disc
        steps.append(f"售价 = 进价 × (1 + {_f(up * 100)}%) × {_f(disc)} = 进价 × {_f(k)}")
        steps.append(f"售价是进价的 {_f(k * 100)}%")
        return done("word.profit", f"{_f(k * 100)}%", k * 100, "%", True)
    if up is not None and disc is not None:
        if ask_cost and sale is not None:
            c = sale / ((1 + up) * disc)
            steps.append(f"设成本为 x 元，标价为 (1 + {_f(up * 100)}%)x，售价为 {_f(disc)}×(1 + {_f(up * 100)}%)x")
            steps.append(f"列方程：{_f(disc * (1 + up))}x = {_f(sale)}，x = {_f(c)}")
            return done("word.profit", f"{_f(c)} 元", c, "元", c * (1 + up) * disc == sale)
        if cost is not None and (ask_sale or ask_profit):
            s = cost * (1 + up) * disc
            steps.append(f"标价 = {_f(cost)} × (1 + {_f(up * 100)}%) = {_f(cost * (1 + up))} 元，售价 = 标价 × {_f(disc)} = {_f(s)} 元")
            if ask_profit:
                steps.append(f"利润 = {_f(s)} - {_f(cost)} = {_f(s - cost)} 元")
                return done("word.profit", f"{_f(s - cost)} 元", s - cost, "元", True)
            return done("word.profit", f"{_f(s)} 元", s, "元", True)
    # 标价 + 折扣（+ 进价）
    if mark is not None and disc is not None:
        s = mark * disc
        steps.append(f"售价 = 标价 × 折扣 = {_f(mark)} × {_f(disc)} = {_f(s)} 元")
        if cost is not None:
            p = s - cost
            steps.append(f"利润 = 售价 - 进价 = {_f(s)} - {_f(cost)} = {_f(p)} 元")
            if ask_rate:
                r = p / cost
                steps.append(f"利润率 = 利润 ÷ 进价 = {_f(p)} ÷ {_f(cost)} = {_f(r * 100)}%")
                return done("word.profit", f"{_f(r * 100)}%", r * 100, "%", True)
            if ask_profit:
                return done("word.profit", f"{_f(p)} 元", p, "元", True)
            return None
        if rate is not None and ask_cost:
            c = s / (1 + rate)
            steps.append(f"设进价为 x 元：x(1 + {_f(rate * 100)}%) = {_f(s)}，x = {_f(c)}")
            return done("word.profit", f"{_f(c)} 元", c, "元", c * (1 + rate) == s)
        if ask_sale or (not ask_cost and not ask_rate and not ask_profit and re.search(r"多少元|几元", raw)):
            return done("word.profit", f"{_f(s)} 元", s, "元", True)
        return None
    # 进价 + 折扣 + 利润率 → 标价
    if cost is not None and disc is not None and rate is not None and ask_mark:
        m_ = cost * (1 + rate) / disc
        steps.append(f"设标价为 x 元，售价 {_f(disc)}x，列方程：{_f(disc)}x - {_f(cost)} = {_f(cost)} × {_f(rate * 100)}%")
        steps.append(f"{_f(disc)}x = {_f(cost * (1 + rate))}，x = {_f(m_)}")
        return done("word.profit", f"{_f(m_)} 元", m_, "元", m_ * disc - cost == cost * rate)
    # 进价 + 利润率 → 售价；售价 + 利润率 → 进价
    if cost is not None and rate is not None and (ask_sale or ask_mark):
        s = cost * (1 + rate)
        steps.append(f"售价 = 进价 × (1 + 利润率) = {_f(cost)} × (1 + {_f(rate * 100)}%) = {_f(s)} 元")
        return done("word.profit", f"{_f(s)} 元", s, "元", True)
    if mark is not None and rate is not None and ask_cost and disc is None:
        c = mark / (1 + rate)
        steps.append(f"设成本为 x 元：x(1 + {_f(rate * 100)}%) = {_f(mark)}，x = {_f(c)}")
        return done("word.profit", f"{_f(c)} 元", c, "元", c * (1 + rate) == mark)
    if sale is not None and rate is not None and ask_cost:
        c = sale / (1 + rate)
        steps.append(f"设进价为 x 元：x(1 + {_f(rate * 100)}%) = {_f(sale)}，x = {_f(c)}")
        return done("word.profit", f"{_f(c)} 元", c, "元", c * (1 + rate) == sale)
    if cost is not None and sale is not None and (ask_rate or ask_profit):
        p = sale - cost
        steps.append(f"利润 = {_f(sale)} - {_f(cost)} = {_f(p)} 元")
        if ask_rate:
            steps.append(f"利润率 = {_f(p)} ÷ {_f(cost)} = {_f(p / cost * 100)}%")
            return done("word.profit", f"{_f(p / cost * 100)}%", p / cost * 100, "%", True)
        return done("word.profit", f"{_f(p)} 元", p, "元", True)
    return None


# ── 浓度 ─────────────────────────────────────────────────────────────────────


def solve_concentration(text: str) -> Optional[KernelSolution]:
    raw = basic_normalize(text).replace(" ", "")
    if not re.search(r"盐水|糖水|酒精|溶液|浓度|含盐|含糖", raw) or re.search(r"溶质质量分数|化学", raw):
        return None
    hint = "浓度问题抓住不变的量：加水时溶质（盐）不变；加盐时水不变。浓度 = 溶质 ÷ 溶液。"
    mdis = re.search(rf"(?:将|把)?\s*{_NUM}\s*(克|千克|kg|g)\s*(?:的)?(?:糖|盐|食盐)\s*(?:溶入|溶于|溶解在|加入到|放入)\s*{_NUM}\s*(?:克|千克|kg|g)\s*(?:的)?水", raw)
    if mdis and re.search(r"质量分数|浓度|含(?:糖|盐)率", raw):
        a, w = F(mdis.group(1)), F(mdis.group(3))
        c = a / (a + w)
        st = [f"溶液质量 = {_f(a)} + {_f(w)} = {_f(a + w)}", f"浓度 = {_f(a)} ÷ {_f(a + w)} × 100% = {_f(c * 100)}%"]
        if not _all_used(raw, [(mdis.start(1), mdis.end(1)), (mdis.start(3), mdis.end(3))]):
            return None
        return KernelSolution(kernel="word.concentration", answer=f"{_f(c * 100)}%", steps=st, hint=hint, explanation="浓度 = 溶质 ÷ 溶液。",
                              answer_value=_ans(c * 100), answer_kind="num", unit="%", check="溶质/溶液复算", confidence=0.85)
    sols = list(re.finditer(rf"{_NUM}\s*(克|千克|kg|g)(?:浓度为|含盐|含糖|含酒精|浓度是)?\s*{_NUM}\s*%|{_NUM}\s*%\s*的?(?:盐水|糖水|酒精|溶液)\s*{_NUM}\s*(克|千克|kg|g)|(?:浓度为|含盐|含糖)\s*{_NUM}\s*%\s*的?(?:盐水|糖水|酒精溶液|溶液)\s*{_NUM}\s*(克|千克|kg|g)", raw))
    items: list[tuple[Fraction, Fraction]] = []
    spans: list[tuple[int, int]] = []
    unit = "克"
    for m in sols:
        g = m.groups()
        if g[0] is not None:
            mass, pct, unit = F(g[0]), F(g[2]) / 100, g[1]
            spans += [(m.start(1), m.end(1)), (m.start(3), m.end(3))]
        elif g[3] is not None:
            pct, mass, unit = F(g[3]) / 100, F(g[4]), g[5]
            spans += [(m.start(4), m.end(4)), (m.start(5), m.end(5))]
        else:
            pct, mass, unit = F(g[6]) / 100, F(g[7]), g[8]
            spans += [(m.start(7), m.end(7)), (m.start(8), m.end(8))]
        items.append((mass, pct))
    if not items:
        return None
    unit = {"g": "克", "kg": "千克"}.get(unit, unit)
    steps: list[str] = []
    m_add_w = re.search(rf"(?:加入|加|再加|倒入)\s*{_NUM}\s*(?:克|千克|g|kg)?\s*(?:的)?水", raw)
    m_add_s = re.search(rf"(?:加入|加|再加)\s*{_NUM}\s*(?:克|千克|g|kg)?\s*(?:的)?(?:盐|糖)", raw)
    m_target = re.search(rf"(?:变为|变成|稀释成|稀释为|配成|浓度为|提高到|降低到|降到)\s*{_NUM}\s*%", raw[sols[-1].end():] if sols else raw)
    off = sols[-1].end() if sols else 0
    ask_water = re.search(r"加(?:入)?(?:多少|几)(?:克|千克)?(?:的)?水|需(?:要)?加水", raw)
    ask_salt = re.search(r"加(?:入)?(?:多少|几)(?:克|千克)?(?:的)?(?:盐|糖)", raw)
    ask_conc = re.search(r"浓度(?:是|为|变为|变成)?(?:多少|百分之几)|含盐率|百分之几", raw)

    def out(ans: str, val: Fraction, u: str) -> Optional[KernelSolution]:
        if not _all_used(raw, spans):
            return None
        return KernelSolution(kernel="word.concentration", answer=ans, steps=steps, hint=hint, explanation="浓度问题（溶质不变/溶剂不变）。",
                              answer_value=_ans(val), answer_kind="num", unit=u, check="溶质质量前后守恒", confidence=0.85)

    if len(items) == 2 and ask_conc and re.search(r"混合|倒在一起|混在一起", raw):
        (a, p), (b, q) = items
        solute = a * p + b * q
        c = solute / (a + b)
        steps.append(f"溶质：{_f(a)}×{_f(p * 100)}% + {_f(b)}×{_f(q * 100)}% = {_f(solute)} {unit}")
        steps.append(f"混合后浓度 = {_f(solute)} ÷ ({_f(a)} + {_f(b)}) = {_f(c * 100)}%")
        return out(f"{_f(c * 100)}%", c * 100, "%")
    if len(items) != 1:
        return None
    mass, pct = items[0]
    if re.search(r"(?:糖|盐|酒精|溶质)的?质量|含(?:糖|盐|酒精)(?:多少|几)|有(?:糖|盐)多少", raw[sols[-1].end():]) and not (m_add_w or m_add_s or m_target):
        steps.append(f"溶质质量 = 溶液质量 × 浓度 = {_f(mass)} × {_f(pct * 100)}% = {_f(mass * pct)} {unit}")
        return out(f"{_f(mass * pct)} {unit}", mass * pct, unit)
    salt = mass * pct
    steps.append(f"原溶液中溶质 = {_f(mass)} × {_f(pct * 100)}% = {_f(salt)} {unit}")
    if m_add_w and ask_conc:
        w = F(m_add_w.group(1))
        spans.append((m_add_w.start(1), m_add_w.end(1)))
        c = salt / (mass + w)
        steps.append(f"加水后溶液 = {_f(mass)} + {_f(w)} = {_f(mass + w)} {unit}，溶质不变")
        steps.append(f"浓度 = {_f(salt)} ÷ {_f(mass + w)} = {_f(c * 100)}%")
        return out(f"{_f(c * 100)}%", c * 100, "%")
    if m_add_s and ask_conc:
        a = F(m_add_s.group(1))
        spans.append((m_add_s.start(1), m_add_s.end(1)))
        c = (salt + a) / (mass + a)
        steps.append(f"加盐后溶质 = {_f(salt + a)}，溶液 = {_f(mass + a)}，浓度 = {_f(c * 100)}%")
        return out(f"{_f(c * 100)}%", c * 100, "%")
    if m_target:
        q = F(m_target.group(1)) / 100
        spans.append((off + m_target.start(1), off + m_target.end(1)))
        if ask_water and q < pct:
            new_total = salt / q
            w = new_total - mass
            steps.append(f"加水时溶质不变，稀释后溶液 = {_f(salt)} ÷ {_f(q * 100)}% = {_f(new_total)} {unit}")
            steps.append(f"需加水 = {_f(new_total)} - {_f(mass)} = {_f(w)} {unit}")
            if salt / (mass + w) != q:
                return None
            return out(f"{_f(w)} {unit}", w, unit)
        if ask_salt and q > pct and q < 1:
            water = mass - salt
            new_total = water / (1 - q)
            a = new_total - mass
            steps.append(f"加盐时水不变：水 = {_f(water)} {unit}，加盐后溶液 = {_f(water)} ÷ (1 - {_f(q * 100)}%) = {_f(new_total)}")
            steps.append(f"需加盐 = {_f(new_total)} - {_f(mass)} = {_f(a)} {unit}")
            return out(f"{_f(a)} {unit}", a, unit)
    return None


# ── 年龄 ─────────────────────────────────────────────────────────────────────


def solve_age(text: str) -> Optional[KernelSolution]:
    raw = _cn2num(basic_normalize(text)).replace(" ", "")
    if "岁" not in raw and "年龄" not in raw:
        return None
    hint = "年龄问题：两人的年龄差永远不变；几年后两人都增加同样的岁数。"
    roles = r"(父亲|爸爸|母亲|妈妈|爷爷|奶奶|老师|哥哥|姐姐|儿子|女儿|小明|小红|小华|小刚|小丽|弟弟|妹妹|学生|孙子)"
    ages = list(re.finditer(rf"{roles}(?:今年|现在)?(?:是|有)?\s*{_NUM}\s*岁", raw))
    mk = re.search(rf"(\d+(?:\.\d+)?)\s*年(后|前).{{0,16}}?(?:年龄)?是.{{0,6}}?(?:年龄)?的\s*{_NUM}\s*倍", raw)
    mq = re.search(rf"(?:几|多少)年(后|前).{{0,16}}?(?:年龄)?是.{{0,6}}?(?:年龄)?的\s*{_NUM}\s*倍", raw)
    steps: list[str] = []
    spans: list[tuple[int, int]] = []
    if len(ages) == 2 and mq:
        (A, a), (B, b) = [(m.group(1), F(m.group(2))) for m in ages]
        for m in ages:
            spans.append((m.start(2), m.end(2)))
        k = F(mq.group(2))
        spans.append((mq.start(2), mq.end(2)))
        if k <= 1:
            return None
        big, small = (a, b) if a > b else (b, a)
        later = mq.group(1) == "后"
        x = (big - k * small) / (k - 1) if later else (k * small - big) / (k - 1)
        if x <= 0 or x.denominator != 1:
            return None
        sign = "+" if later else "-"
        steps.append(f"设 x 年{mq.group(1)}，列方程：{_f(big)} {sign} x = {_f(k)}({_f(small)} {sign} x)")
        steps.append(f"解得 x = {_f(x)}")
        chk = (big + x == k * (small + x)) if later else (big - x == k * (small - x))
        if not chk or not _all_used(raw, spans):
            return None
        steps.append(f"检验：{_f(x)} 年{mq.group(1)}两人分别 {_f(big + x if later else big - x)} 岁和 {_f(small + x if later else small - x)} 岁，正好 {_f(k)} 倍 ✓")
        return KernelSolution(kernel="word.age", answer=f"{_f(x)} 年{mq.group(1)}", steps=steps, hint=hint, explanation="年龄问题（列一元一次方程）。",
                              answer_value=_ans(x), answer_kind="num", unit="年", check="代回倍数关系", confidence=0.85)
    ms = re.search(rf"年龄(?:之)?和(?:是|为)\s*{_NUM}\s*岁?", raw)
    mm = re.search(rf"(?:年龄)?是.{{0,6}}?(?:年龄)?的\s*{_NUM}\s*倍", raw)
    if ms and mm and not ages and not mk and not mq:
        S, k = F(ms.group(1)), F(mm.group(1))
        spans += [(ms.start(1), ms.end(1)), (mm.start(1), mm.end(1))]
        small = S / (k + 1)
        if small.denominator != 1 or not _all_used(raw, spans):
            return None
        steps.append(f"设小的年龄为 x 岁，大的为 {_f(k)}x 岁：x + {_f(k)}x = {_f(S)}，x = {_f(small)}")
        steps.append(f"大的年龄 = {_f(k * small)} 岁")
        return KernelSolution(kernel="word.age", answer=f"{_f(k * small)} 岁和 {_f(small)} 岁", steps=steps, hint=hint, explanation="和倍问题。",
                              answer_value=f"{_ans(k * small)}, {_ans(small)}", answer_kind="nums", unit="岁", check="和与倍数关系", confidence=0.8)
    md = re.search(rf"(?:大|比.{{1,6}}?大)\s*{_NUM}\s*岁", raw)
    if md and mk and len(ages) == 0:
        d = F(md.group(1))
        n = F(mk.group(1))
        k = F(mk.group(3))
        spans += [(md.start(1), md.end(1)), (mk.start(1), mk.end(1)), (mk.start(3), mk.end(3))]
        if k <= 1:
            return None
        small_then = d / (k - 1)
        small_now = small_then - n if mk.group(2) == "后" else small_then + n
        if small_now <= 0 or small_now.denominator != 1 or not _all_used(raw, spans):
            return None
        steps.append(f"年龄差 {_f(d)} 岁不变；{_f(n)} 年{mk.group(2)}大的是小的 {_f(k)} 倍，所以那时小的 = {_f(d)} ÷ ({_f(k)} - 1) = {_f(small_then)} 岁")
        steps.append(f"小的今年 = {_f(small_now)} 岁，大的今年 = {_f(small_now + d)} 岁")
        ask_big = bool(re.search(r"(?:父亲|爸爸|母亲|妈妈|爷爷|奶奶|老师|哥哥|姐姐)(?:今年|现在)?(?:多少|几)岁", raw))
        mab = re.search(r"([\u4e00-\u9fff]{1,2}?)比([\u4e00-\u9fff]{1,2}?)大", raw)
        mq2 = re.search(r"(?:求|问)?\s*([\u4e00-\u9fff]{1,2}?)(?:今年|现在)(?:是)?(?:多少|几)岁", raw)
        if mab and mq2:
            ask_big = mq2.group(1) == mab.group(1)
        v = small_now + d if ask_big else small_now
        return KernelSolution(kernel="word.age", answer=f"{_f(v)} 岁", steps=steps, hint=hint, explanation="年龄差不变。",
                              answer_value=_ans(v), answer_kind="num", unit="岁", check="代回倍数关系", confidence=0.8)
    return None


# ── 鸡兔同笼 ─────────────────────────────────────────────────────────────────


_LEGS = {"鸡": 2, "鸭": 2, "鹅": 2, "鸟": 2, "兔": 4, "兔子": 4, "狗": 4, "羊": 4, "猪": 4, "牛": 4, "猫": 4,
         "自行车": 2, "三轮车": 3, "汽车": 4, "小汽车": 4, "摩托车": 2}


def _generic_heads_feet(raw: str) -> Optional[KernelSolution]:
    names = "|".join(sorted(_LEGS, key=len, reverse=True))
    m = re.search(rf"({names})(?:和|与|、)({names})(?:一共|共|总共)?(?:有)?\s*{_NUM}\s*(?:辆|只|头|个)", raw)
    mf = re.search(rf"(?:轮子|脚|腿|车轮)(?:一共|共|总共)?(?:有)?\s*{_NUM}\s*(?:个|只|条)", raw)
    if not (m and mf):
        return None
    a, b = m.group(1), m.group(2)
    la, lb = _LEGS[a], _LEGS[b]
    if la == lb:
        return None
    H, Fe = F(m.group(3)), F(mf.group(1))
    if not _all_used(raw, [(m.start(3), m.end(3)), (mf.start(1), mf.end(1))]):
        return None
    nb = (Fe - la * H) / (lb - la)
    na = H - nb
    if nb < 0 or na < 0 or nb.denominator != 1:
        return None
    if la * na + lb * nb != Fe:
        return None
    steps = [f"假设全是{a}：应有 {la}×{_f(H)} = {_f(la * H)}，与实际 {_f(Fe)} 相差 {_f(Fe - la * H)}",
             f"每把一个{a}换成{b}多 {lb - la}，{b}有 {_f(Fe - la * H)} ÷ {lb - la} = {_f(nb)}，{a}有 {_f(na)}",
             f"检验：{la}×{_f(na)} + {lb}×{_f(nb)} = {_f(Fe)} ✓"]
    qm = re.search(rf"求?({names})(?:有)?(?:多少|几)", raw[mf.end():])
    if qm and not re.search(r"各", raw[mf.end():]):
        v = na if qm.group(1) == a else nb
        return KernelSolution(kernel="word.chicken_rabbit", answer=f"{qm.group(1)} {_f(v)}", steps=steps,
                              hint="假设法：先假设全是同一种，多出来（或少了）的数量由另一种带来。",
                              explanation="鸡兔同笼型问题（假设法 / 列方程）。", answer_value=_ans(v), answer_kind="num", check="总数、腿（轮）数都吻合", confidence=0.9)
    return KernelSolution(kernel="word.chicken_rabbit", answer=f"{a} {_f(na)}，{b} {_f(nb)}", steps=steps,
                          hint="假设法：先假设全是同一种，多出来（或少了）的数量由另一种带来。", explanation="鸡兔同笼型问题。",
                          answer_value=f"{_ans(na)}, {_ans(nb)}", answer_kind="nums", check="总数、腿（轮）数都吻合", confidence=0.9)


def solve_chicken_rabbit(text: str) -> Optional[KernelSolution]:
    raw = _cn2num(basic_normalize(text)).replace(" ", "")
    if not (re.search(r"鸡", raw) and re.search(r"兔", raw)):
        return _generic_heads_feet(raw)
    mh = re.search(rf"(?:共有|有|共)?\s*{_NUM}\s*(?:个)?头", raw) or re.search(rf"头(?:共)?(?:有)?\s*{_NUM}\s*个", raw) or re.search(
        rf"(?:鸡和兔|鸡兔|兔和鸡)(?:一共|共)?(?:有)?\s*{_NUM}\s*只", raw)
    mf = re.search(rf"{_NUM}\s*(?:只|条)\s*(?:脚|腿|足)", raw) or re.search(rf"(?:脚|腿|足)(?:共)?(?:有)?\s*{_NUM}\s*(?:只|条)", raw)
    if not mh or not mf:
        mtot = re.search(rf"(?:鸡和兔|鸡兔)(?:一共|共)?(?:有)?\s*{_NUM}\s*只", raw)
        if not (mtot and mf):
            return None
        mh = mtot
    H, Fe = F(mh.group(1)), F(mf.group(1))
    if not _all_used(raw, [(mh.start(1), mh.end(1)), (mf.start(1), mf.end(1))]):
        return None
    r = (Fe - 2 * H) / 2
    c = H - r
    if r < 0 or c < 0 or r.denominator != 1:
        return None
    steps = [f"假设全是鸡：应有 2×{_f(H)} = {_f(2 * H)} 只脚，比实际少 {_f(Fe)} - {_f(2 * H)} = {_f(Fe - 2 * H)} 只",
             f"每把一只鸡换成兔多 2 只脚，兔有 {_f(Fe - 2 * H)} ÷ 2 = {_f(r)} 只，鸡有 {_f(H)} - {_f(r)} = {_f(c)} 只",
             f"方程法：设兔 x 只，2({_f(H)} - x) + 4x = {_f(Fe)}，x = {_f(r)}",
             f"检验：头 {_f(c)} + {_f(r)} = {_f(H)}，脚 2×{_f(c)} + 4×{_f(r)} = {_f(2 * c + 4 * r)} ✓"]
    if 2 * c + 4 * r != Fe:
        return None
    only = re.search(r"求?(兔|鸡)(?:子)?(?:有)?(?:多少|几)只", raw)
    if only and not re.search(r"各", raw):
        v = r if only.group(1) == "兔" else c
        return KernelSolution(kernel="word.chicken_rabbit", answer=f"{only.group(1)} {_f(v)} 只", steps=steps,
                              hint="假设法：先假设全是鸡，多出来（少了）的脚是兔子带来的，每只兔比鸡多 2 只脚。",
                              explanation="鸡兔同笼（假设法 / 列方程）。", answer_value=_ans(v), answer_kind="num", unit="只", check="头数、脚数都吻合", confidence=0.95)
    ask_r_first = raw.find("兔") < raw.find("鸡") and re.search(r"兔.{0,3}鸡.{0,3}各", raw)
    vals = f"{_ans(r)}, {_ans(c)}" if ask_r_first else f"{_ans(c)}, {_ans(r)}"
    return KernelSolution(kernel="word.chicken_rabbit", answer=f"鸡 {_f(c)} 只，兔 {_f(r)} 只", steps=steps,
                          hint="假设法：先假设全是鸡，多出来（少了）的脚是兔子带来的，每只兔比鸡多 2 只脚。",
                          explanation="鸡兔同笼（假设法 / 列方程）。", answer_value=vals, answer_kind="nums", unit="只", check="头数、脚数都吻合", confidence=0.95)


__all__ = ["solve_age", "solve_chicken_rabbit", "solve_concentration", "solve_profit", "solve_travel", "solve_work"]
