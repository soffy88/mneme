"""
广东高中数学知识点字典 (Knowledge Component Dictionary)
========================================================
适用：广东省新高考（3+1+2），数学全国统一命题（新课标Ⅰ卷），人教A版教材。

这是整个算法内核（KT + FSRS）的地基。没有干净统一的 KC 编码，
掌握度建模和复习调度都无从谈起。

每个 KC 字段说明：
- kc_id        : 唯一编码  GDMATH-<模块>-<序号>
- name         : 知识点名称
- module       : 所属教材模块
- grade        : 建议年级（高一/高二/高三，对应必修/选必/复习）
- parent       : 父知识点 kc_id（None 表示顶层）
- prerequisites: 前置 kc_id 列表（支撑跨学段衔接分析与 DKT 迁移建模；
                 MID-* 表示初中阶段知识点，作为跨学段占位）
- question_types: 该 KC 常见题型 ['choice','fill','solve']
- gaokao_score : 高考中该 KC 的历年平均分值（估算，单位：分，满分150）
- bkt          : 该 KC 的 BKT 先验参数 {p_init, p_transit, p_guess, p_slip}
                 注意：p_guess 与题型强相关（选择题易蒙对），下方按主导题型设置。

BKT 先验设置原则（冷启动）：
- p_init   : 入学前已掌握概率。基础知识点高，综合/压轴知识点低。
- p_transit: 一次有效练习的学习增益。难知识点低（更难学会）。
- p_guess  : 选择题主导 ~0.25；填空 ~0.05；解答题 ~0.02。
- p_slip   : 已掌握却失误的概率。计算繁琐的知识点 slip 偏高。
"""

KC_LIST = [
    # ============ 必修第一册（高一上）============
    {
        "kc_id": "GDMATH-SET-01", "name": "集合的概念与运算",
        "module": "必修一·集合与逻辑", "grade": "高一", "parent": None,
        "prerequisites": [], "question_types": ["choice", "fill"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.45, "p_transit": 0.35, "p_guess": 0.25, "p_slip": 0.08},
    },
    {
        "kc_id": "GDMATH-SET-02", "name": "常用逻辑用语（充分必要条件）",
        "module": "必修一·集合与逻辑", "grade": "高一", "parent": None,
        "prerequisites": ["GDMATH-SET-01"], "question_types": ["choice"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.30, "p_transit": 0.30, "p_guess": 0.25, "p_slip": 0.10},
    },
    {
        "kc_id": "GDMATH-INEQ-01", "name": "一元二次不等式与基本不等式",
        "module": "必修一·方程不等式", "grade": "高一", "parent": None,
        "prerequisites": ["MID-QUAD-EQ"], "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 8,
        "bkt": {"p_init": 0.30, "p_transit": 0.28, "p_guess": 0.15, "p_slip": 0.12},
    },
    {
        "kc_id": "GDMATH-FUNC-01", "name": "函数的概念与定义域值域",
        "module": "必修一·函数", "grade": "高一", "parent": None,
        "prerequisites": ["MID-FUNC-BASIC"], "question_types": ["choice", "fill"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.25, "p_transit": 0.25, "p_guess": 0.20, "p_slip": 0.10},
    },
    {
        "kc_id": "GDMATH-FUNC-02", "name": "函数的单调性奇偶性周期性",
        "module": "必修一·函数", "grade": "高一", "parent": None,
        "prerequisites": ["GDMATH-FUNC-01"], "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 8,
        "bkt": {"p_init": 0.20, "p_transit": 0.22, "p_guess": 0.20, "p_slip": 0.12},
    },
    {
        "kc_id": "GDMATH-FUNC-03", "name": "指数函数与对数函数",
        "module": "必修一·函数", "grade": "高一", "parent": None,
        "prerequisites": ["GDMATH-FUNC-01"], "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 8,
        "bkt": {"p_init": 0.22, "p_transit": 0.24, "p_guess": 0.18, "p_slip": 0.12},
    },
    {
        "kc_id": "GDMATH-TRIG-01", "name": "三角函数的图象与性质",
        "module": "必修一·三角函数", "grade": "高一", "parent": None,
        "prerequisites": ["GDMATH-FUNC-02"], "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 10,
        "bkt": {"p_init": 0.18, "p_transit": 0.20, "p_guess": 0.18, "p_slip": 0.14},
    },
    {
        "kc_id": "GDMATH-TRIG-02", "name": "三角恒等变换",
        "module": "必修一·三角函数", "grade": "高一", "parent": None,
        "prerequisites": ["GDMATH-TRIG-01"], "question_types": ["fill", "solve"],
        "gaokao_score": 7,
        "bkt": {"p_init": 0.15, "p_transit": 0.18, "p_guess": 0.05, "p_slip": 0.16},
    },

    # ============ 必修第二册（高一下）============
    {
        "kc_id": "GDMATH-VEC-01", "name": "平面向量及其运算",
        "module": "必修二·平面向量", "grade": "高一", "parent": None,
        "prerequisites": ["GDMATH-TRIG-01"], "question_types": ["choice", "fill"],
        "gaokao_score": 8,
        "bkt": {"p_init": 0.20, "p_transit": 0.24, "p_guess": 0.20, "p_slip": 0.12},
    },
    {
        "kc_id": "GDMATH-TRIG-03", "name": "解三角形（正弦余弦定理）",
        "module": "必修二·平面向量", "grade": "高一", "parent": None,
        "prerequisites": ["GDMATH-TRIG-02", "GDMATH-VEC-01"],
        "question_types": ["fill", "solve"], "gaokao_score": 12,
        "bkt": {"p_init": 0.18, "p_transit": 0.22, "p_guess": 0.05, "p_slip": 0.15},
    },
    {
        "kc_id": "GDMATH-COMPLEX-01", "name": "复数",
        "module": "必修二·复数", "grade": "高一", "parent": None,
        "prerequisites": ["GDMATH-INEQ-01"], "question_types": ["choice"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.30, "p_transit": 0.35, "p_guess": 0.25, "p_slip": 0.08},
    },
    {
        "kc_id": "GDMATH-SOLID-01", "name": "立体几何初步（线面位置关系）",
        "module": "必修二·立体几何", "grade": "高一", "parent": None,
        "prerequisites": [], "question_types": ["choice", "solve"],
        "gaokao_score": 10,
        "bkt": {"p_init": 0.18, "p_transit": 0.20, "p_guess": 0.18, "p_slip": 0.13},
    },
    {
        "kc_id": "GDMATH-STAT-01", "name": "统计（抽样与数字特征）",
        "module": "必修二·统计", "grade": "高一", "parent": None,
        "prerequisites": [], "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.30, "p_transit": 0.30, "p_guess": 0.18, "p_slip": 0.10},
    },
    {
        "kc_id": "GDMATH-PROB-01", "name": "古典概型与概率初步",
        "module": "必修二·概率", "grade": "高一", "parent": None,
        "prerequisites": [], "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.25, "p_transit": 0.26, "p_guess": 0.15, "p_slip": 0.11},
    },

    # ============ 选择性必修第一册（高二上）============
    {
        "kc_id": "GDMATH-SVEC-01", "name": "空间向量与立体几何",
        "module": "选必一·空间向量", "grade": "高二", "parent": None,
        "prerequisites": ["GDMATH-VEC-01", "GDMATH-SOLID-01"],
        "question_types": ["solve"], "gaokao_score": 12,
        "bkt": {"p_init": 0.15, "p_transit": 0.20, "p_guess": 0.02, "p_slip": 0.16},
    },
    {
        "kc_id": "GDMATH-LINE-01", "name": "直线与方程",
        "module": "选必一·解析几何", "grade": "高二", "parent": None,
        "prerequisites": ["GDMATH-FUNC-01"], "question_types": ["choice", "fill"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.25, "p_transit": 0.26, "p_guess": 0.18, "p_slip": 0.12},
    },
    {
        "kc_id": "GDMATH-CIRCLE-01", "name": "圆的方程",
        "module": "选必一·解析几何", "grade": "高二", "parent": None,
        "prerequisites": ["GDMATH-LINE-01"], "question_types": ["choice", "fill"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.22, "p_transit": 0.24, "p_guess": 0.18, "p_slip": 0.12},
    },
    {
        "kc_id": "GDMATH-CONIC-01", "name": "椭圆",
        "module": "选必一·圆锥曲线", "grade": "高二", "parent": None,
        "prerequisites": ["GDMATH-CIRCLE-01"], "question_types": ["fill", "solve"],
        "gaokao_score": 8,
        "bkt": {"p_init": 0.15, "p_transit": 0.18, "p_guess": 0.05, "p_slip": 0.15},
    },
    {
        "kc_id": "GDMATH-CONIC-02", "name": "双曲线",
        "module": "选必一·圆锥曲线", "grade": "高二", "parent": None,
        "prerequisites": ["GDMATH-CONIC-01"], "question_types": ["choice", "fill"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.14, "p_transit": 0.17, "p_guess": 0.18, "p_slip": 0.15},
    },
    {
        "kc_id": "GDMATH-CONIC-03", "name": "抛物线",
        "module": "选必一·圆锥曲线", "grade": "高二", "parent": None,
        "prerequisites": ["GDMATH-CONIC-01"], "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.14, "p_transit": 0.17, "p_guess": 0.12, "p_slip": 0.15},
    },
    {
        "kc_id": "GDMATH-CONIC-04", "name": "圆锥曲线综合（压轴）",
        "module": "选必一·圆锥曲线", "grade": "高三", "parent": None,
        "prerequisites": ["GDMATH-CONIC-01", "GDMATH-CONIC-02", "GDMATH-CONIC-03"],
        "question_types": ["solve"], "gaokao_score": 10,
        "bkt": {"p_init": 0.06, "p_transit": 0.10, "p_guess": 0.01, "p_slip": 0.20},
    },

    # ============ 选择性必修第二册（高二下）============
    {
        "kc_id": "GDMATH-SEQ-01", "name": "等差数列与等比数列",
        "module": "选必二·数列", "grade": "高二", "parent": None,
        "prerequisites": ["GDMATH-FUNC-01"], "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 10,
        "bkt": {"p_init": 0.20, "p_transit": 0.24, "p_guess": 0.12, "p_slip": 0.13},
    },
    {
        "kc_id": "GDMATH-SEQ-02", "name": "数列求和与综合（压轴）",
        "module": "选必二·数列", "grade": "高三", "parent": None,
        "prerequisites": ["GDMATH-SEQ-01"], "question_types": ["solve"],
        "gaokao_score": 7,
        "bkt": {"p_init": 0.08, "p_transit": 0.12, "p_guess": 0.01, "p_slip": 0.18},
    },
    {
        "kc_id": "GDMATH-DERIV-01", "name": "导数的概念与运算",
        "module": "选必二·导数", "grade": "高二", "parent": None,
        "prerequisites": ["GDMATH-FUNC-03"], "question_types": ["choice", "fill"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.18, "p_transit": 0.22, "p_guess": 0.15, "p_slip": 0.12},
    },
    {
        "kc_id": "GDMATH-DERIV-02", "name": "导数的应用（单调极值最值）",
        "module": "选必二·导数", "grade": "高三", "parent": None,
        "prerequisites": ["GDMATH-DERIV-01", "GDMATH-FUNC-02"],
        "question_types": ["solve"], "gaokao_score": 12,
        "bkt": {"p_init": 0.10, "p_transit": 0.14, "p_guess": 0.02, "p_slip": 0.17},
    },
    {
        "kc_id": "GDMATH-DERIV-03", "name": "导数压轴（含参讨论与不等式证明）",
        "module": "选必二·导数", "grade": "高三", "parent": None,
        "prerequisites": ["GDMATH-DERIV-02"], "question_types": ["solve"],
        "gaokao_score": 10,
        "bkt": {"p_init": 0.05, "p_transit": 0.08, "p_guess": 0.01, "p_slip": 0.22},
    },

    # ============ 选择性必修第三册（高二下/高三）============
    {
        "kc_id": "GDMATH-COUNT-01", "name": "计数原理（排列组合二项式）",
        "module": "选必三·计数原理", "grade": "高二", "parent": None,
        "prerequisites": ["GDMATH-PROB-01"], "question_types": ["choice", "fill"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.16, "p_transit": 0.20, "p_guess": 0.18, "p_slip": 0.15},
    },
    {
        "kc_id": "GDMATH-PROB-02", "name": "随机变量及其分布（离散型期望方差）",
        "module": "选必三·概率分布", "grade": "高三", "parent": None,
        "prerequisites": ["GDMATH-PROB-01", "GDMATH-COUNT-01"],
        "question_types": ["solve"], "gaokao_score": 12,
        "bkt": {"p_init": 0.12, "p_transit": 0.16, "p_guess": 0.03, "p_slip": 0.15},
    },
    {
        "kc_id": "GDMATH-STAT-02", "name": "成对数据的统计分析（回归与独立性检验）",
        "module": "选必三·统计分析", "grade": "高三", "parent": None,
        "prerequisites": ["GDMATH-STAT-01"], "question_types": ["solve"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.18, "p_transit": 0.22, "p_guess": 0.04, "p_slip": 0.12},
    },
]

# 初中阶段前置知识点占位（用于跨学段衔接分析；MVP 不展开，仅作 prerequisites 引用）
MIDDLE_SCHOOL_KC_STUBS = {
    "MID-QUAD-EQ": "一元二次方程（初中）",
    "MID-FUNC-BASIC": "函数基础与一次/反比例函数（初中）",
}

# ---- 索引与工具函数 ----
KC_INDEX = {kc["kc_id"]: kc for kc in KC_LIST}


def get_kc(kc_id):
    return KC_INDEX.get(kc_id)


def get_bkt_prior(kc_id):
    """返回某 KC 的 BKT 先验参数；未知 KC 给一个保守默认。"""
    kc = KC_INDEX.get(kc_id)
    if kc:
        return dict(kc["bkt"])
    return {"p_init": 0.20, "p_transit": 0.20, "p_guess": 0.15, "p_slip": 0.12}


def all_prerequisites(kc_id, _seen=None):
    """递归取出某 KC 的全部前置（含跨学段），用于衔接断层分析。"""
    if _seen is None:
        _seen = set()
    kc = KC_INDEX.get(kc_id)
    if not kc:
        return []
    for p in kc.get("prerequisites", []):
        if p not in _seen:
            _seen.add(p)
            all_prerequisites(p, _seen)
    return list(_seen)


def total_gaokao_score():
    return sum(kc["gaokao_score"] for kc in KC_LIST)


def kc_summary():
    return {
        "total_kc": len(KC_LIST),
        "by_grade": {
            g: len([k for k in KC_LIST if k["grade"] == g])
            for g in ["高一", "高二", "高三"]
        },
        "total_gaokao_score_covered": total_gaokao_score(),
        "modules": sorted(set(k["module"] for k in KC_LIST)),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(kc_summary(), ensure_ascii=False, indent=2))
    print("\n示例：椭圆压轴的全部前置链：")
    print(all_prerequisites("GDMATH-CONIC-04"))
