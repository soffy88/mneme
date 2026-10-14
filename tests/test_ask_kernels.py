"""拍照问题目确定性内核（services.ask_kernels）的单元测试：纯函数，不需要数据库，不调用 LLM。"""

from __future__ import annotations

import pytest

from services.ask_kernels import solve_text, split_questions
from services.ask_kernels.variants import grade_answer, make_variant

CASES = [
    # (题面, kernel 前缀, answer_value)
    ("计算：-2² + |−3| × (−1/3) − (0.5)^2 ÷ 1/4", "arith", "-6"),
    ("计算：(-2)² + 4 × 3 = ?", "arith", "16"),
    ("计算：sin30° + cos²45° - tan60°", "arith", "1-sqrt(3)"),
    ("化简：1/(√3-1)", "arith", "(1+sqrt(3))/2"),
    ("用科学记数法表示 0.000032", "arith.sci", "0.000032"),
    ("解方程：3(x-2)+1=2x-3", "algebra.linear_eq", "x=2"),
    ("解方程 (x-1)/2 - (2x+1)/3 = 1", "algebra.linear_eq", "x=-11"),
    ("解方程：x²-5x+6=0", "algebra.quadratic_eq", "2, 3"),
    ("解方程：2/(x-1) = 3/x", "algebra.fractional_eq", "x=3"),
    ("解方程：x/(x - 1) = 2/(x - 1) + 1", "algebra.fractional_eq", "无解"),
    ("解方程 |2x-1| = 5", "algebra.abs_eq", "-2, 3"),
    ("已知关于x的一元二次方程x²-2x+m=0有两个相等的实数根，求m的值", "algebra.quadratic_param", "1"),
    ("设x1,x2是方程x²-3x-4=0的两个根，求x1+x2和x1·x2", "algebra.vieta", "3, -4"),
    ("解不等式组：{2x+1>3, 3x-2≤7}，并写出它的整数解", "algebra.inequality_system", "2, 3"),
    ("解方程组：{2x+y=5, x-y=1}", "algebra.linear_system_2", "x=2, y=1"),
    ("解方程组 x+y+z=6, 2x-y+z=3, x+2y-z=2", "algebra.linear_system_3", "x=1, y=2, z=3"),
    ("因式分解：3x^3-12x", "algebra.factor", "3*x*(x-2)*(x+2)"),
    ("先化简，再求值：(1 - 1/(x+1)) ÷ x/(x²-1)，其中 x=3", "algebra.simplify_eval", "2"),
    ("已知一次函数的图象经过点(1,3)和(2,5)，求这个一次函数的解析式", "function.linear", "2*x+1"),
    ("求二次函数y=x²-4x+3的顶点坐标和对称轴", "function.quadratic", "2, -1, 2"),
    ("已知y是x的反比例函数，当x=2时y=6，求当x=-3时y的值", "function.inverse", "-4"),
    ("在Rt△ABC中，∠C=90°，∠A=30°，AB=10，求BC的长", "geometry.right_triangle_trig", "5"),
    ("一个直角三角形的两条直角边分别为6cm和8cm，求斜边的长", "geometry.pythagoras", "10"),
    ("扇形的圆心角为120°，半径为6，求扇形的弧长", "geometry.sector", "4*pi"),
    ("一个多边形的内角和是1080°，求这个多边形的边数", "geometry.polygon", "8"),
    ("△ABC∽△DEF，AB=3，DE=6，BC=4，求EF的长", "geometry.similar", "8"),
    ("求数据 3, 5, 7, 7, 8 的平均数、中位数和众数", "stats.descriptive", "6, 7, 7"),
    ("同时掷两枚骰子，点数之和为7的概率", "prob.two_step", "1/6"),
    ("某厂产值从100万元增长到121万元，求两年的平均增长率", "ratio.growth_rate", "10"),
    ("72km/h = ( ) m/s", "unit.convert", "20"),
    ("鸡兔同笼，共有35个头，94只脚，鸡和兔各有多少只？", "word.chicken_rabbit", "23, 12"),
    ("小明以每分钟60米的速度从家出发去学校，5分钟后爸爸以每分钟160米的速度骑车去追，爸爸几分钟能追上小明？", "word.travel_chase", "3"),
    ("一项工程，甲队单独做需要10天完成，乙队单独做需要15天完成，两队合作需要几天完成？", "word.work", "6"),
    ("一件商品标价200元，打八折出售，仍可获利25%，这件商品的进价是多少元？", "word.profit", "128"),
    ("有200克浓度为10%的盐水，加入多少克水后浓度变为8%？", "word.concentration", "50"),
    ("父亲今年40岁，儿子今年12岁，几年后父亲的年龄是儿子年龄的3倍？", "word.age", "2"),
    ("质量为60kg的人站在水平地面上，双脚与地面的接触面积为0.04m²，求他对地面的压强。", "physics.pressure", "15000"),
    ("一个体积为500cm³的铁块浸没在水中，求它受到的浮力。", "physics.buoyancy", "5"),
    ("用滑轮组将重600N的物体匀速提升2m，绳子自由端的拉力为250N，承担物重的绳子有3段，求滑轮组的机械效率。", "physics.work_power", "80"),
    ("质量为2kg的水温度从20℃升高到70℃，吸收的热量是多少？", "physics.heat", "420000"),
    ("R1=10Ω，R2=20Ω串联在6V的电源上，求电路中的电流", "physics.ohm", "0.2"),
    ("一盏标有“220V 100W”的灯泡正常工作10h，消耗多少kW·h的电能？", "physics.electric_power", "1"),
    ("求NH4NO3中氮元素的质量分数", "chemistry.mass_fraction", "35"),
    ("把50g质量分数为20%的硫酸溶液稀释成10%的溶液，需要加水多少克？", "chemistry.dilution", "50"),
    ("实验室用13g锌与足量稀硫酸反应 Zn + H2SO4 = ZnSO4 + H2↑，生成氢气多少克？", "chemistry.stoichiometry", "0.4"),
    ("配平：Fe + O₂ → Fe₃O₄", "chemistry.balance", "3, 2, 1"),
]


@pytest.mark.parametrize("text,kernel,value", CASES)
def test_kernel_solves(text: str, kernel: str, value: str) -> None:
    sol = solve_text(text)
    assert sol is not None, text
    assert sol.kernel.startswith(kernel), (text, sol.kernel)
    assert sol.answer_value == value, (text, sol.answer_value)
    assert sol.verified and sol.steps and sol.hint


NEGATIVE = [
    "今天天气很好",
    "速度 v = 3 m/s，求路程",
    "__import__('os').system('id') = 1",
    "x = (lambda: 1)()",
    "物体质量为2×10^3 kg，求重力是多少吨",  # 问法与单位不匹配的物理题不应被算术内核抢答
    "把 405000 用科学记数法表示，写成 a×10^n 的形式，其中 1≤a<10",
    "等腰三角形有一个角为50°，求它的顶角",  # 需要分类讨论
    "两列火车从相距 480 千米的两站同时出发相向而行，速度分别为 80 千米/时和 100 千米/时，问出发多少小时后两车相距 60 千米？",
    "用 50 N 的力把重 200 N 的物体沿斜面匀速推到 4 m 高处，斜面长 5 m，求这个斜面的机械效率",  # 数据矛盾 η>1
]


@pytest.mark.parametrize("text", NEGATIVE)
def test_kernel_abstains(text: str) -> None:
    sol = solve_text(text)
    # 允许解出 n=5 这类明确问法；只要求“不确定的不乱答”
    if text.startswith("把 405000"):
        assert sol is None or sol.answer_value in ("5", "405000")
        return
    assert sol is None, (text, sol and sol.answer)


def test_split_questions_numbered_and_subparts() -> None:
    qs = split_questions("1. 计算 1+2\n2. 解方程 2x=4\n3. 因式分解 x²-1")
    assert [q["label"] for q in qs] == ["1", "2", "3"]
    sub = split_questions("已知二次函数y=x²-2x-3。(1)求顶点坐标；(2)求与x轴的交点坐标")
    assert len(sub) == 2 and all("y=x²-2x-3" in q["text"] for q in sub)
    assert split_questions("计算 3.5+1.2 = ?") == []


def test_variant_is_same_kernel_and_clean() -> None:
    v = make_variant("解方程：x²-5x+6=0", 1)
    assert v is not None
    assert v["kernel"] == "algebra.quadratic_eq"
    assert v["text"] != "解方程：x²-5x+6=0"
    again = make_variant("解方程：x²-5x+6=0", 1)
    assert again == v  # 确定性
    sol = solve_text(v["text"])
    assert sol is not None and sol.answer_value == v["solution"]["answer_value"]


@pytest.mark.parametrize(
    "student,value,kind,unit,ok",
    [
        ("x=2", "x=2", "nums", "", True),
        ("x1=3,x2=2", "2, 3", "nums", "", True),
        ("0.5", "1/2", "num", "", True),
        ("2√3", "2*sqrt(3)", "num", "", True),
        ("25π", "25*pi", "num", "", True),
        ("20%", "20", "num", "%", True),
        ("(x+2)(x+3)", "(x+2)*(x+3)", "expr", "", True),
        ("x^2+5x+6", "(x+2)*(x+3)", "expr", "", False),
        ("1<x≤3", "1<x<=3", "ineq", "", True),
        ("x>1", "1<x<=3", "ineq", "", False),
        ("没有实数根", "无实数根", "text", "", True),
        ("3", "x=2", "nums", "", False),
    ],
)
def test_grade_answer(student: str, value: str, kind: str, unit: str, ok: bool) -> None:
    assert grade_answer(student, value, kind, unit) is ok


def test_similar_questions_bank_lookup() -> None:
    from services.ask_kernels.similar import similar_questions

    out = similar_questions("一个水池有进水管和出水管，进水管4小时注满，出水管6小时放完，同时打开几小时注满？")
    assert isinstance(out, list)
    for q in out:
        assert q["text"] and q["answer"]
