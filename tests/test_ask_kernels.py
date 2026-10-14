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


# ── 题库扫描（bank_scan）发现的答非所问：内核必须弃答（或不给出当时的错答） ─────────────────
# (题面原文, 当时给错的内核, 当时的错答)；题面保留题库里的 LaTeX 写法
BANK_OFF_TARGET = [
    ("算 804-197 的差大约是 ( )。", "arith.rational", "607"),
    ("一个四位数的密码, 它的大小在 2000 与 3000 之间, 百位数字是 0 , 十位与个位数字相同, 它们两个的和是 8 , 这个密码是 $(\\quad)$ 。", "arith.compare", "3000"),
    ("(2021-浙江瑞安$\\cdot$开学考试) 若 $\\left\\{\\begin{array}{l}x=a \\\\ y=b\\end{array}\\right.$ 是方程组 $\\left\\{\\begin{array}{l}2 x+3 y=-5 \\\\ 2 x-3 y=7\\end{array}\\right.$ 的解, 则代数式 $9 b^{2}-4 a^{2}$ 的值是\n\n##", "algebra.linear_system_2", "x=1/2, y=-2"),
    ("一个圆的周长是 31.4 米, 半径增加 1 米后, 面积增加了 $\\qquad$平方米.", "geometry.circle", "24649/(100*pi)"),
    ("关于 $x$ 的一元二次方程 $(m-5) x^{2}+2 x+2=0$ 有实根, 则 $m$ 的最大整数解是 \\$ \\qquad \\$ .", "algebra.linear_eq", "x=-1"),
    ("若 $m(m-2)=3$, 则 $(m-1)^{2}$ 的值是", "algebra.quadratic_eq", "-1, 3"),
    ("若实数 $x$ 满足 $x^{2}-2 x-1=0$, 则 $2 x^{3}-7 x^{2}+4 x-2020$ 的值为", "algebra.linear_eq", "x=-1/2"),
    ("若 $\\triangle A B C$ 的周长为 20 , 面积为 32 , 则 $\\triangle A B C$ 的内切圆半径为", "geometry.circle", "100/pi"),
    ("在一个不透明的盒子中装有许多球, 它们除颜色不同外, 其余均相同. 已知有 8 个白球, 若从中随机摸出一个球, 它是白球的概率为 $\\frac{2}{3}$, 盒中共有球 $\\qquad$个.\n\n##", "prob.classical", "1"),
    ("在一张边长是 6 分米的正方形纸上裁出一个最大的圆, 这个圆的面积是 （）平方分米。", "geometry.square", "36"),
    ("若 $m$ 是方程 $x^{2}-4 x+1=0$ 的一个根, 则 $3 m^{2}-12 m+2020$ 的值为", "algebra.linear_eq", "x=1/4"),
    ("已知 $a$ 是方程 $x^{2}-3 x-1=0$ 的一个根, 则代数式 $-2 a^{2}+6 a-3$ 的值是", "algebra.linear_eq", "x=-1/3"),
    ("403-298$ 的结果大约是 $(\\quad)$", "arith.rational", "105"),
    ("在一个不透明的口袋中,装有若干个除颜色不同外，其余都相同的小球。如果口袋中装有3个红球且从中随机摸出一个球是红球的概率为$frac{1}{5}$,那么口袋中小球共有$qquad$个.", "prob.classical", "1"),
    ("袋子里有 4 个黑球, $m$ 个白球, 它们除颜色外都相同. 经过大量实验, 从中任取一个球恰好是黑球的概率是 $\\frac{1}{2}$, 则 $m$ 的值是 $\\qquad$ .", "prob.classical", "1"),
    ("一个长方形长 10 厘米, 宽 8 厘米, 在里面剪一个最大的半圆, 这个半圆的周长是 $\\qquad$厘米。", "geometry.rectangle", "36"),
    ("已知直线 $l_{1}$ 经过点 $A(0,-1)$ 和点 $B\\left(\\frac{4}{a}, 1\\right)$, 直线 $l_{2}$ 经过点 $M(1,1)$ 和点 $N(0,-2)$, 若 $l_{1}$ 与 $l_{2}$ 没有公共点,则实数 $a$ 的值为", "function.linear", "2*x-1"),
    ("三个互不相等的有理数, 既可以表示为 $1, a+b, b$ 的形式, 又可以表示为 $0, \\frac{a}{b}$, $a$ 的形式, 且 $|x|=3$, 求 $(a+b)^{2020}+(a b)^{2021}-(a+b-a b)+x^{2}$ 的值为 \\$ \\qquad \\$ .", "algebra.abs_eq", "-3, 3"),
    ("7. 在直角坐标系中, 曲线 $C_{1}$ 的参数方程为 $\\left\\{\\begin{array}{c}x=\\cos \\alpha \\\\ y=1+2 \\sin \\alpha\\end{array}\\right.$ ( $\\alpha$ 为参数), 在极坐标系中, $C_{2}$的方程为 $\\rho(3 \\cos \\theta-4 \\sin \\theta)=6$, 则 $C_{1}$ 与 $C_{2}$ 的交点个数为", "algebra.linear_eq", "y=3"),
    ("$\\sin \\frac{13 \\pi}{6}+\\cos \\frac{13 \\pi}{3}-\\tan \\left(-\\frac{23 \\pi}{4}\\right)$ 的值为 \\$ \\qquad \\$ .", "arith.real", "49*pi/4"),
    ("一个长 $8 \\mathrm{~cm}$ 、宽 $5 \\mathrm{~cm}$ 的长方形按 $5: 1$ 的比例放大后，得到的图形的面积是 $\\qquad$ .", "geometry.rectangle", "40"),
    ("(2021-浙江瑞安$\\cdot$开学考试) 若 $\\left\\{\\begin{array}{l}x=a \\\\ y=b\\end{array}\\right.$ 是方程组 $\\left\\{\\begin{array}{l}2 x+3 y=-5 \\\\ 2 x-3 y=7\\end{array}\\right.$ 的解, 则代数式 $9 b^{2}-4 a^{2}$ 的值是\n\n##", "algebra.linear_system_2", "x=1/2, y=-2"),
    ("已知 $a_{2} \\frac{1}{9}=\\frac{4}{9}$, 则 $\\log _{\\frac{2}{3}} a=$", "algebra.quadratic_eq", "-2, 2"),
    ("一张半圆形纸片的周长是 $20.56 \\mathrm{~cm}$ ，它的半径是 $\\qquad$ ) cm，面积是 $\\qquad$ ) $\\mathrm{cm}^{2}$ 。", "geometry.circle", "66049/(1250*pi)"),
    ("坐标平面上一机器人在行进中始终保持到两点 $A(a, 0)$ (其中 $a \\in \\mathbf{R}$ ) 和 $B(0,1)$ 的距离相等, 且机器人也始终接触不到直线 $l: y=x+1$, 则 $a$ 的值为 \\$ \\qquad \\$", "function.linear", "x+1"),
    ("6. 方程 $x+\\sin x=0$ 的根有 \\$ \\qquad \\$个.", "algebra.linear_eq", "x=0"),
    ("当 $a=3, b=-\\frac{1}{3}$ 时, $(a+b)^{2}+(a+b)(a-b)-2 a^{2}=$", "algebra.linear_system_2", "a=3, b=-1/3"),
    ("小北在计算 “ $5+3 \\times 9$ ” 时, 从左到右依次计算, 算出的结果与正确答案相差 ( )。", "arith.rational", "32"),
    ("已知抛物线 $y=x^{2}$ 与直线 $y=(k+2) x+1-2 k$ 的两个不同交点分别为 $A\\left(x_{1}, y_{1}\\right)$, $B\\left(x_{2}, y_{2}\\right)$. 若 $x_{1}$ 和 $x_{2}$ 均为整数, 则实数 $k$ 的值为 $\\qquad$ .\n\n##", "function.quadratic", "0, 0, 0"),
    ("在一个边长是 $10 \\mathrm{~cm}$ 的正方形中剪去一个最大的圆, 剩下部分的面积（） $\\mathrm{cm}^{2}$ 。", "geometry.square", "100"),
    ("在一个比例中，两个内项互为倒数，如果一个外项是 $\\frac{1}{10}$ ，那么另一个外项是 )。 $\\qquad$", "arith.real", "1/10"),
    ("一个半圆的周长是 $10.28 \\mathrm{dm}$, 这个半圆的面积是 $\\qquad$ $\\mathrm{dm}^{2}$ 。", "geometry.circle", "66049/(5000*pi)"),
    ("求值: $\\log _{4} 16+16^{\\frac{1}{2}}=$", "arith.real", "420"),
    ("$\\frac{\\lg 3+2 \\lg 2-1}{\\lg 1.2}=$", "arith.rational", "20"),
    ("用二分法求方程 $x^{2}-5=0$ 在区间 $(2,3)$ 内的近似解, 经过\\qquad次二分后精确度能达到 0.01 .", "algebra.quadratic_eq", "-sqrt(5), sqrt(5)"),
    ("计算 $100\\left(\\frac{1}{2} \\lg 9-\\lg 2\\right)-\\log _{9} 8 \\cdot \\log _{4} \\sqrt[3]{3}=$", "arith.radical", "250-6272*sqrt(3)"),
    ("一组数据 $2,3,4,5, \\ldots, 2016$ 的中位数为 \\$ \\qquad \\$", "stats.descriptive", "3.5"),
    ("已知扇形的周长是 $4 \\mathrm{~cm}$, 则扇形面积最大时, 扇形的中心角的弧度数是", "geometry.circle", "4/pi"),
    ("小明用 $s^{2}=\\frac{1}{10}\\left[\\left(x_{1}-3\\right)^{2}+\\left(x_{2}-3\\right)^{2}+\\cdots+\\left(x_{10}-3\\right)^{2}\\right]$ 计算一组数据的方差,那么 $x_{1}+x_{2}+\\cdots+x_{10}=$ \\$ \\qquad \\$", "algebra.vieta", "0"),
    ("一个圆环的外圆半径是 $10 \\mathrm{~cm}$, 内圆半径是 $8 \\mathrm{~cm}$, 它的面积是 $\\qquad$。", "geometry.circle", "100*pi"),
    ("二次函数 $y=(x-2)(5-2 x)$ 的二次项系数是 $\\qquad$", "function.quadratic", "9/4, 1/8, 9/4"),
    ("当 $x=\\sqrt{3}+1$ 时, 式子 $x^{2}-2 x+2$ 的值为", "algebra.linear_eq", "x=1+sqrt(3)"),
    ("已知二次函数 $y=-x^{2}+10 x-21$, 当 $6 \\leq x \\leq 12$ 时，函数的最大值是 $\\qquad$ .", "function.quadratic", "4"),
    ("6.$sin 95^{\\circ}+\\cos 175^{\\circ}$ 的值为", "arith.trig", "cos(pi/36)+175"),
    ("一个半圆的周长是 $25.7 \\mathrm{~cm}$, 这个半圆的面积是 $\\qquad$ $\\mathrm{cm}^{2}$ 。", "geometry.circle", "66049/(800*pi)"),
    ("（2020 秋 -龙凤区校级月考）如下一组数据： $10,12,25,10,30,10,13$; 则该组数据的中位数与众数的差为", "stats.descriptive", "12, 10"),
    ("如图所示, 一个正四棱雉(底面是正方形, 从顶点向底面引垂线, 垂足是底面中心的四棱雉)的正方形底面的边长为 $4 \\mathrm{~cm}$, 高与斜高的夹角为 $30^{\\circ}$, 则正四棱雉的表面积为 $\\mathrm{cm}^{2}$.\n\n<ImageHere>", "geometry.square", "16"),
    ("如图, 二次函数 $y=x^{2}-4 x+3$ 的图象交 $x$ 轴于 $A 、 B$ 两点, 交 $y$ 轴于点 $C, \\triangle A B C$ 的面积为 $\\qquad$\n\n<ImageHere>\n\n##", "function.quadratic", "2, -1, 2"),
    ("在一个半径是 $3 \\mathrm{~cm}$ 的圆中画一个扇形, 如右图。弧 $\\mathrm{AB}$ 的长度是 $6.28 \\mathrm{~cm}$, 这个扇形的面积是 ( ) cm²\n\n<ImageHere>", "geometry.circle", "9*pi"),
    ("如图, 正方形 $A B C D$ 的边长为 $2, M N / / B C$ 分别交 $A B 、 C D$ 于点 $M 、 N$, 在 $M N$ 上任取两点 $P 、 Q$,那么图中阴影部分的面积是 \\$ \\qquad \\$ .\n\n<ImageHere>", "geometry.square", "4"),
    ("抛物线 $y=\\frac{1}{16} x^{2}$ 的焦点与双曲线 $\\frac{x^{2}}{3}-\\frac{y^{2}}{m}=-1$ 的上焦点重合, 则 $m=$ \\$ \\qquad \\$ .\n\n18 如图, 过抛物线 $y^{2}=2 p x(p>0)$ 的焦点 $F$ 的直线 $l$ 依次交抛物线及其准线于点 $A, B, C$, 若 $|B C|=2|B F|$, 且 $|A F|=3$, 则抛物线的方程是 \\$ \\qquad \\$ .", "function.quadratic", "0, 0, 0"),
    ("如图, 在一个长 $20 m$, 宽 $10 m$ 的矩形草地内修建宽度相等的小路 (阴影部分),若剩余草地（空白部分）的面积 $171 m^{2}$, 则小路的宽度为 m.\n\n<ImageHere>", "geometry.rectangle", "200"),
    ("生物学研究表明, 在一定的温度范围内, 酶的活性会随温度的升高逐渐增强; 在最适温度时, 酶的活性最强; 超过一定温度范围, 酶的活性又随温度的开高逐渐减弱, 甚至会失去活性$\\cdot$现已知某种酶的活性值 $y$ (单位: $1 \\mathrm{U}$ ) 与温度 $x$ (单位: ${ }^{\\circ} \\mathrm{C}$ ) 的关系可以近似用二次函数 $y=-\\frac{1}{2} x^{2}+14 x+142$来表示, 则当温度为最适宜温度时, 该种酶的活性值为 $\\qquad$ $\\mathrm{IU}$.\n\n<ImageHere>", "function.quadratic", "14, 240, 14"),
]


@pytest.mark.parametrize("text,kernel,wrong", BANK_OFF_TARGET)
def test_bank_scan_off_target_abstains(text: str, kernel: str, wrong: str) -> None:
    sol = solve_text(text, "math")
    assert sol is None or sol.answer_value != wrong, (kernel, sol and sol.kernel, sol and sol.answer_value)


@pytest.mark.parametrize(
    "text,kernel,value",
    [
        # LaTeX 题面能被识别（题库/教辅文本）
        ("关于 $x$ 的一元二次方程 $(m-5) x^{2}+2 x+2=0$ 有实根, 则 $m$ 的最大整数解是 \\$ \\qquad \\$ .", "algebra.quadratic_param", "4"),
        ("二次函数 $y=(x-4)^{2}+9$ 的最小值是 $\\qquad$", "function.quadratic", "9"),
        ("计算: $\\left(\\frac{65}{7}+\\frac{65}{9}\\right) \\div\\left(\\frac{5}{7}+\\frac{5}{9}\\right)$", "arith", "13"),
        # 小学圆：周长是 3.14 的整数倍 → 按 π≈3.14
        ("一个圆的周长是 31.4 米，它的面积是多少平方米？", "geometry.circle", "157/2"),
    ],
)
def test_latex_and_pi_314(text: str, kernel: str, value: str) -> None:
    sol = solve_text(text, "math")
    assert sol is not None and sol.kernel.startswith(kernel), sol
    assert sol.answer_value.replace(" ", "") == value


def test_latex_to_plain() -> None:
    from services.ask_kernels.core import latex_to_plain

    assert latex_to_plain("x^{2}-2 x-1=0") == "x^2-2 x-1=0"
    assert latex_to_plain("$\\frac{2}{3}$") == "(2)/(3)"
    assert latex_to_plain("$x_{1}+x_{2}$") == "x1+x2"
    assert latex_to_plain("$64^{\\circ}$") == "64°"
    assert latex_to_plain("计算：(-2/3) + (-1/6).") == "计算：(-2/3) + (-1/6)."  # 无 LaTeX 原样返回


@pytest.mark.parametrize(
    "text,subject",
    [
        ("apple 是什么意思", "english"),
        ("go 的过去式是什么", "english"),
        ("She ___ (go) to school every day.", "english"),
        ("He is ___ honest boy. A. a B. an C. the", "english"),
        ("床前明月光的下一句是什么", "chinese"),
        ("《静夜思》的作者是谁", "chinese"),
        ("给“重”字注音", "chinese"),
        ("画蛇添足是什么意思", "chinese"),
        ("守株待兔", "chinese"),
        ("解方程 2x+3=7", "math"),
        ("计算 3/4 + 1/2", "math"),
    ],
)
def test_guess_subject_provider_subjects(text: str, subject: str) -> None:
    from services.photo_ask_service import guess_subject

    assert guess_subject(text) == subject
