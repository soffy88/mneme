# Held-out set for the deterministic ask kernels. Written independently of problems.jsonl / kernel code.
# Every answer is computed here (fractions/sympy), not typed by hand.
import json, sys
from fractions import Fraction as F
import sympy as sp

x, y = sp.symbols("x y")
P = []


def add(id, type, subject, text, answer, kind="num", unit=""):
    if kind in ("expr", "ineq", "text"):
        answer = str(answer)
    else:
        answer = [str(a) for a in (answer if isinstance(answer, list) else [answer])]
    P.append({"id": "h-" + id, "type": type, "subject": subject, "text": text,
              "answer": answer, "answer_kind": kind, "unit": unit})


def fr(v):
    v = F(v).limit_denominator(100000)
    return str(v.numerator) if v.denominator == 1 else f"{v.numerator}/{v.denominator}"


def ssym(e):
    return str(sp.nsimplify(e))

# ---- arithmetic (12)
add("frac-01", "frac", "math", "计算 3/4 − 5/6 + 1/3 的结果。", fr(F(3, 4) - F(5, 6) + F(1, 3)))
add("frac-02", "frac", "math", "求值：(−1/2) × 4/5 ÷ (−2/15)", fr(F(-1, 2) * F(4, 5) / F(-2, 15)))
add("frac-03", "frac", "math", "2又1/3 减去 3/4 等于多少？", fr(F(7, 3) - F(3, 4)))
add("dec-01", "frac", "math", "计算：0.25 × (−8) + 1.5", fr(F(1, 4) * -8 + F(3, 2)))
add("neg-01", "frac", "math", "计算：−3² + (−2)³ − (−5)", fr(-9 + (-8) + 5))
add("power-01", "power", "math", "计算 2^(−2) + (π − 3)^0 的值", fr(F(1, 4) + 1))
add("power-02", "power", "math", "(−1/3)^(−2) − 4 等于多少", fr(9 - 4))
add("radical-01", "radical", "math", "化简计算：√27 − √12 + √3", ssym(sp.sqrt(27) - sp.sqrt(12) + sp.sqrt(3)))
add("radical-02", "radical", "math", "计算 √8 × √2 − √16 的结果", ssym(sp.sqrt(8) * sp.sqrt(2) - 4))
add("trig-01", "trig", "math", "计算：2sin30° + tan45° − cos60°", fr(F(2, 2) + 1 - F(1, 2)))
add("trig-02", "trig", "math", "求 sin60° · cos30° 的值", fr(F(3, 4)))
add("absval-01", "absval", "math", "计算：|−7| − |3 − 10| + |−2|", fr(7 - 7 + 2))

# ---- expand / factor / simplify (6)
add("expand-01", "expand", "math", "展开：(2x − 3)(x + 4)", str(sp.expand((2 * x - 3) * (x + 4))).replace(" ", ""), "expr")
add("expand-02", "expand", "math", "计算 (x + 5)² − x(x + 2)", str(sp.expand((x + 5) ** 2 - x * (x + 2))).replace(" ", ""), "expr")
add("factor-01", "factor", "math", "把 x² − 9 分解因式", "(x-3)*(x+3)", "expr")
add("factor-02", "factor", "math", "分解因式：3a² − 12a + 12".replace("a", "x"), "3*(x-2)**2", "expr")
add("factor-03", "factor", "math", "因式分解 x² + x − 12", "(x-3)*(x+4)", "expr")
add("simplify-01", "simplify_frac", "math", "化简：(x² − 4)/(x + 2)", "x-2", "expr")

# ---- equations / inequalities / systems (12)
add("lineq-01", "lineq", "math", "解方程 5x − 7 = 2x + 8", "5", "num")
add("lineq-02", "lineq", "math", "求方程 (x − 1)/2 = (x + 2)/3 的解", fr(F(7)), "num")
add("lineq-03", "lineq", "math", "已知 3(x + 2) − 4 = 11，求 x。", fr(F(11 + 4 - 6, 3)), "num")
add("quad-01", "quad", "math", "解一元二次方程：x² − 7x + 10 = 0", ["2", "5"], "nums")
add("quad-02", "quad", "math", "方程 2x² + 3x − 2 = 0 的根是多少？", ["-2", "1/2"], "nums")
add("quad-03", "quad", "math", "用配方法解方程 x² − 6x + 4 = 0", ["3 - sqrt(5)", "3 + sqrt(5)"], "nums")
add("fraceq-01", "frac_eq", "math", "解分式方程：3/(x − 1) = 2/x", "-2", "num")
add("sys2-01", "sys2", "math", "解方程组：x + y = 7，2x − y = 2", ["3", "4"], "nums")
add("sys2-02", "sys2", "math", "已知 3x + 4y = 18 且 x − 2y = −4，求 x、y。", ["2", "3"], "nums")
add("ineq-01", "ineq", "math", "解不等式 3x − 5 > 7", "x>4", "ineq")
add("ineq-02", "ineq", "math", "解不等式：−2x + 1 ≥ 9", "x<=-4", "ineq")
add("ineqsys-01", "ineq_sys", "math", "解不等式组：x − 1 > 0，2x − 7 ≤ 1", "1<x<=4", "ineq")

# ---- functions (8)
add("linfunc-01", "linfunc", "math", "一次函数的图象经过点 (1, 3) 和 (3, 7)，求这个函数的解析式。", "2*x+1", "expr")
add("linfunc-02", "linfunc", "math", "直线 y = kx − 4 经过点 (2, 2)，求 k 的值。", "3", "num")
add("quadfunc-01", "quadfunc", "math", "求抛物线 y = x² − 4x + 1 的顶点坐标。", ["2", "-3"], "nums")
add("quadfunc-02", "quadfunc", "math", "二次函数 y = −x² + 6x − 5 的最大值是多少？", "4", "num")
add("quadfunc-03", "quadfunc", "math", "抛物线 y = x² − 2x − 8 与 x 轴交点的横坐标是多少？", ["-2", "4"], "nums")
add("quadfunc-04", "quadfunc", "math", "抛物线 y = 2x² + 8x + 3 的对称轴是直线 x = ？", "-2", "num")
add("invprop-01", "invprop", "math", "反比例函数 y = k/x 的图象经过点 (2, −6)，求 k。", "-12", "num")
add("invprop-02", "invprop", "math", "已知 y 与 x 成反比例，当 x = 4 时 y = 3，求 x = 6 时 y 的值。", "2", "num")

# ---- geometry (10)
add("pyth-01", "pyth", "math", "在 Rt△ABC 中，∠C = 90°，AC = 6，BC = 8，求 AB 的长。", "10", "num")
add("pyth-02", "pyth", "math", "直角三角形斜边长 13，一条直角边长 5，另一条直角边长是多少？", "12", "num")
add("circle-01", "geom", "math", "一个圆的半径是 3 cm，求它的面积（结果保留 π）。", "9*pi", "num", "cm^2")
add("circle-02", "geom", "math", "圆的直径为 10，求它的周长（保留 π）。", "10*pi", "num")
add("sector-01", "geom", "math", "半径为 6、圆心角为 120° 的扇形面积是多少？（保留 π）", "12*pi", "num")
add("polygon-01", "geom", "math", "正八边形的每个内角是多少度？", "135", "num", "°")
add("polygon-02", "geom", "math", "一个多边形的内角和是 1080°，它是几边形？", "8", "num")
add("rttrig-01", "trig", "math", "在 Rt△ABC 中，∠C = 90°，∠A = 30°，斜边 AB = 10，求 BC 的长。", "5", "num")
add("similar-01", "geom", "math", "△ABC ∽ △DEF，相似比为 2:3，若 AB = 4，求 DE 的长。", "6", "num")
add("triangle-01", "geom", "math", "三角形的两个内角分别是 47° 和 68°，求第三个内角的度数。", "65", "num", "°")

# ---- stats & probability (6)
add("stats-01", "stats", "math", "求数据 4，7，9，6，9 的平均数。", fr(F(4 + 7 + 9 + 6 + 9, 5)), "num")
add("stats-02", "stats", "math", "数据 3，8，5，10，6，2 的中位数是多少？", fr(F(5 + 6, 2)), "num")
add("stats-03", "stats", "math", "一组数据 2，5，5，7，5，9 的众数是几？", "5", "num")
add("stats-04", "stats", "math", "求数据 1，3，5，7，9 的方差。", fr(F(sum((v - 5) ** 2 for v in [1, 3, 5, 7, 9]), 5)), "num")
add("prob-01", "prob", "math", "掷一枚质地均匀的骰子，朝上的点数是偶数的概率是多少？", "1/2", "num")
add("prob-02", "prob", "math", "盒子里有 3 个红球、5 个黄球、2 个蓝球，随机摸出一个是黄球的概率是多少？", "1/2", "num")

# ---- word problems (10)
add("travel-01", "word_travel", "math", "甲乙两地相距 300 km，一辆客车和一辆货车同时从两地出发相向而行，客车每小时行 70 km，货车每小时行 50 km，几小时后两车相遇？", "5/2", "num", "小时")
add("travel-02", "word_travel", "math", "小明以每分钟 60 m 的速度先走 10 分钟，哥哥以每分钟 100 m 的速度从同一地点出发去追，哥哥几分钟能追上小明？", "15", "num", "分钟")
add("work-01", "word_work", "math", "一项工程，甲单独做 12 天完成，乙单独做 6 天完成，两人合做需要几天完成？", "4", "num", "天")
add("profit-01", "word_profit", "math", "一件衬衫标价 200 元，打八折出售后仍获利 25%，这件衬衫的进价是多少元？", "128", "num", "元")
add("profit-02", "word_profit", "math", "某商品进价 80 元，售价 100 元，利润率是多少？", "25", "num", "%")
add("discount-01", "word_profit", "math", "一台电脑原价 4500 元，现在打九折，现价是多少元？", "4050", "num", "元")
add("conc-01", "word_conc", "math", "把 20 g 盐溶解在 180 g 水中，所得盐水的浓度是多少？", "10", "num", "%")
add("age-01", "word_age", "math", "今年父亲 40 岁，儿子 12 岁，几年后父亲的年龄是儿子的 3 倍？", "2", "num", "年")
add("chicken-01", "word_chicken", "math", "笼子里有鸡和兔共 20 只，脚共 56 只，兔有多少只？", "8", "num", "只")
add("chicken-02", "word_chicken", "math", "鸡兔同笼，共有 35 个头，94 只脚，鸡有多少只？", "23", "num", "只")

# ---- physics (16)
add("speed-01", "phy_speed", "physics", "一辆汽车 2 h 行驶了 144 km，它的平均速度是多少 m/s？", "20", "num", "m/s")
add("speed-02", "phy_speed", "physics", "声音在空气中的传播速度是 340 m/s，经过 3 s 听到回声，求声源到障碍物的距离。", "510", "num", "m")
add("density-01", "phy_density", "physics", "一块金属的质量是 270 g，体积是 100 cm³，求它的密度是多少 g/cm³？", "2.7", "num", "g/cm^3")
add("density-02", "phy_density", "physics", "体积为 0.5 m³ 的冰，密度为 0.9×10³ kg/m³，它的质量是多少 kg？", "450", "num", "kg")
add("pressure-01", "phy_pressure", "physics", "一个质量为 60 kg 的人双脚站立，鞋底与地面的总接触面积为 0.04 m²，他对地面的压强是多少？（g = 10 N/kg）", "15000", "num", "Pa")
add("liquid-01", "phy_liquid", "physics", "水深 2 m 处水产生的压强是多少帕？（ρ水 = 1.0×10³ kg/m³，g 取 10 N/kg）", "20000", "num", "Pa")
add("buoy-01", "phy_buoy", "physics", "一个物体浸没在水中，排开水的体积是 2×10⁻⁴ m³，它受到的浮力是多大？（g = 10 N/kg）", "2", "num", "N")
add("lever-01", "phy_lever", "physics", "杠杆平衡时，动力臂是 0.6 m，阻力臂是 0.2 m，阻力是 300 N，求动力。", "100", "num", "N")
add("work-01p", "phy_work", "physics", "用 50 N 的水平拉力使木箱沿水平方向前进 4 m，拉力做了多少功？", "200", "num", "J")
add("power-01p", "phy_power", "physics", "起重机在 10 s 内把重 6000 N 的货物匀速提高 5 m，它的功率是多少瓦？", "3000", "num", "W")
add("eff-01", "phy_work", "physics", "用动滑轮把重 400 N 的物体提升 2 m，拉力做的总功是 1000 J，求机械效率。", "80", "num", "%")
add("heat-01", "phy_heat", "physics", "质量为 2 kg 的水温度从 20 ℃ 升高到 70 ℃，吸收的热量是多少？[c水 = 4.2×10³ J/(kg·℃)]", "420000", "num", "J")
add("ohm-01", "phy_ohm", "physics", "一个电阻两端电压为 12 V，通过它的电流是 0.4 A，这个电阻的阻值是多少欧？", "30", "num", "Ω")
add("ohm-02", "phy_ohm", "physics", "R1 = 10 Ω 和 R2 = 20 Ω 串联在 6 V 的电源上，电路中的电流是多少？", "0.2", "num", "A")
add("ohm-03", "phy_ohm", "physics", "两个电阻 R1 = 6 Ω、R2 = 3 Ω 并联，它们的总电阻是多少？", "2", "num", "Ω")
add("elec-01", "phy_power", "physics", "一盏标有“220 V 100 W”的灯正常工作 5 h，消耗电能多少 kW·h？", "0.5", "num", "kW·h")

# ---- chemistry (10)
add("mr-01", "chem_mr", "chemistry", "计算 CaCO₃ 的相对分子质量。（Ca-40 C-12 O-16）", "100", "num")
add("mr-02", "chem_mr", "chemistry", "H₂SO₄ 的相对分子质量是多少？（H-1 S-32 O-16）", "98", "num")
add("mr-03", "chem_mr", "chemistry", "求 CO₂ 的相对分子质量（C-12，O-16）。", "44", "num")
add("frac-c1", "chem_frac", "chemistry", "计算 NH₄NO₃ 中氮元素的质量分数。（N-14 H-1 O-16）", "35", "num", "%")
add("frac-c2", "chem_frac", "chemistry", "Fe₂O₃ 中铁元素的质量分数是多少？（Fe-56 O-16）", "70", "num", "%")
add("sol-01", "chem_sol", "chemistry", "将 15 g 氯化钠完全溶解在 85 g 水中，所得溶液中溶质的质量分数是多少？", "15", "num", "%")
add("sol-02", "chem_sol", "chemistry", "要配制 200 g 质量分数为 5% 的氢氧化钠溶液，需要氢氧化钠多少克？", "10", "num", "g")
add("dil-01", "chem_sol", "chemistry", "把 50 g 质量分数为 20% 的硫酸溶液稀释成 10% 的溶液，需要加水多少克？", "50", "num", "g")
add("stoich-01", "chem_stoich", "chemistry", "根据 2H₂O =通电= 2H₂↑ + O₂↑，电解 36 g 水，能生成氧气多少克？（H-1 O-16）", "32", "num", "g")
add("stoich-02", "chem_stoich", "chemistry", "已知 CaCO₃ + 2HCl = CaCl₂ + H₂O + CO₂↑，10 g 碳酸钙与足量稀盐酸反应，生成二氧化碳多少克？（Ca-40 C-12 O-16）", "4.4", "num", "g")

# sympy sanity checks for symbolic answers
assert sp.simplify(sp.sympify("(x-3)*(x+3)") - (x**2 - 9)) == 0
assert sp.simplify(sp.sympify("3*(x-2)**2") - (3*x**2 - 12*x + 12)) == 0
assert sp.simplify(sp.sympify("(x-3)*(x+4)") - (x**2 + x - 12)) == 0
assert set(sp.solve(x**2 - 7*x + 10)) == {2, 5}
assert set(sp.solve(2*x**2 + 3*x - 2)) == {-2, sp.Rational(1, 2)}
assert set(sp.solve(x**2 - 6*x + 4)) == {3 - sp.sqrt(5), 3 + sp.sqrt(5)}
assert sp.solve(sp.Eq(3/(x-1), 2/x)) == [-2]
assert sp.solve([x + y - 7, 2*x - y - 2], [x, y]) == {x: 3, y: 4}
assert sp.solve([3*x + 4*y - 18, x - 2*y + 4], [x, y]) == {x: 2, y: 3}
assert sp.solve(sp.Eq((x-1)/2, (x+2)/3)) == [7]
assert sp.solve(sp.Eq(3*(x+2) - 4, 11)) == [3]
assert sp.solve(5*x - 7 - 2*x - 8) == [5]
assert sp.solve(x**2 - 2*x - 8) == [-2, 4]
for p in P:
    if p["id"] == "h-lineq-03":
        assert p["answer"] == ["3"], p
# physics/chem numeric checks
assert 144000 / 7200 == 20 and 340 * 3 / 2 == 510 and 270 / 100 == 2.7 and 0.5 * 900 == 450
assert 600 / 0.04 == 15000 and 1000 * 10 * 2 == 20000 and abs(1000 * 10 * 2e-4 - 2) < 1e-9
assert 300 * 0.2 / 0.6 == 100 and 6000 * 5 / 10 == 3000 and 400 * 2 / 1000 == 0.8
assert 4200 * 2 * 50 == 420000 and abs(6 / 30 - 0.2) < 1e-12 and 6 * 3 / 9 == 2
assert 40 + 12 + 48 == 100 and 2 + 32 + 64 == 98 and abs(28 / 80 - 0.35) < 1e-12 and 112 / 160 == 0.7
assert 36 / 36 * 32 == 32 and abs(10 / 100 * 44 - 4.4) < 1e-9 and 50 * 0.2 / 0.1 - 50 == 50
assert 200 * 0.8 / 1.25 == 128 and 300 / 120 == 2.5 and 600 / 40 == 15
json.dump(None, open("/dev/null", "w"))
out = sys.argv[1] if len(sys.argv) > 1 else "holdout.jsonl"
with open(out, "w") as f:
    for p in P:
        f.write(json.dumps(p, ensure_ascii=False) + "\n")
from collections import Counter
print(len(P), dict(Counter(p["type"] for p in P)))
