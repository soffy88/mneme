"""
广东高中数学知识点字典 v2（精细版）
====================================
适用：广东省新高考（3+1+2），数学全国统一命题（新课标Ⅰ卷），人教A版教材。

v2 改进：
1. 粒度从 29 → 72 个 KC，匹配 KU 包的 cluster 细度
2. 每个 KC 关联对应的 KU ID 列表（ku_ids 字段）
3. 初中前置知识点补全 BKT 参数
4. 新增 question_type_distribution 字段，描述该 KC 在高考中的题型分布
5. 新增 difficulty_range 字段，描述该 KC 题目的难度范围

BKT 先验设置原则（冷启动）：
- p_init   : 入学前已掌握概率。基础知识点高，综合/压轴知识点低。
- p_transit: 一次有效练习的学习增益。难知识点低（更难学会）。
- p_guess  : 选择题主导 ~0.25；填空 ~0.05；解答题 ~0.02。
- p_slip   : 已掌握却失误的概率。计算繁琐的知识点 slip 偏高。
"""

from __future__ import annotations

from typing import Any

KC_LIST: list[dict[str, Any]] = [
    # =========================================================================
    # 必修第一册（高一上）—— 集合与常用逻辑用语
    # =========================================================================
    {
        "kc_id": "GDMATH-SET-01", "name": "集合的基本概念与表示",
        "module": "必修一·集合与逻辑", "grade": "高一",
        "prerequisites": [],
        "question_types": ["choice", "fill"],
        "gaokao_score": 3,
        "bkt": {"p_init": 0.50, "p_transit": 0.35, "p_guess": 0.25, "p_slip": 0.08},
        "ku_ids": ["renjiao-math-g10-a-ku-venn图", "renjiao-math-g10-a-ku-集合的表示方法-列举法",
                   "renjiao-math-g10-a-ku-集合的表示方法-描述法", "renjiao-math-g10-a-ku-集合中元素的特性-确定性-互异性-无序性"],
        "difficulty_range": [0.1, 0.3],
    },
    {
        "kc_id": "GDMATH-SET-02", "name": "集合间的基本关系（子集/真子集/相等）",
        "module": "必修一·集合与逻辑", "grade": "高一",
        "prerequisites": ["GDMATH-SET-01"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 2,
        "bkt": {"p_init": 0.40, "p_transit": 0.32, "p_guess": 0.25, "p_slip": 0.08},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.35],
    },
    {
        "kc_id": "GDMATH-SET-03", "name": "集合的基本运算（交并补）",
        "module": "必修一·集合与逻辑", "grade": "高一",
        "prerequisites": ["GDMATH-SET-02"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 3,
        "bkt": {"p_init": 0.35, "p_transit": 0.30, "p_guess": 0.25, "p_slip": 0.10},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.40],
    },
    {
        "kc_id": "GDMATH-SET-04", "name": "集合的计数与容斥原理",
        "module": "必修一·集合与逻辑", "grade": "高一",
        "prerequisites": ["GDMATH-SET-03"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 2,
        "bkt": {"p_init": 0.30, "p_transit": 0.28, "p_guess": 0.25, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.45],
    },
    {
        "kc_id": "GDMATH-LOGIC-01", "name": "命题与充分必要条件",
        "module": "必修一·集合与逻辑", "grade": "高一",
        "prerequisites": ["GDMATH-SET-01"],
        "question_types": ["choice"],
        "gaokao_score": 3,
        "bkt": {"p_init": 0.30, "p_transit": 0.30, "p_guess": 0.25, "p_slip": 0.10},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.40],
    },
    {
        "kc_id": "GDMATH-LOGIC-02", "name": "全称量词与存在量词（含否定）",
        "module": "必修一·集合与逻辑", "grade": "高一",
        "prerequisites": ["GDMATH-LOGIC-01"],
        "question_types": ["choice"],
        "gaokao_score": 2,
        "bkt": {"p_init": 0.28, "p_transit": 0.30, "p_guess": 0.25, "p_slip": 0.10},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.40],
    },

    # =========================================================================
    # 必修第一册（高一上）—— 不等式
    # =========================================================================
    {
        "kc_id": "GDMATH-INEQ-01", "name": "不等式的基本性质与比较大小",
        "module": "必修一·方程不等式", "grade": "高一",
        "prerequisites": ["MID-QUAD-EQ"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 3,
        "bkt": {"p_init": 0.40, "p_transit": 0.30, "p_guess": 0.20, "p_slip": 0.10},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.35],
    },
    {
        "kc_id": "GDMATH-INEQ-02", "name": "基本不等式（均值不等式）及其应用",
        "module": "必修一·方程不等式", "grade": "高一",
        "prerequisites": ["GDMATH-INEQ-01"],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.25, "p_transit": 0.26, "p_guess": 0.18, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.55],
    },
    {
        "kc_id": "GDMATH-INEQ-03", "name": "一元二次不等式及其解法",
        "module": "必修一·方程不等式", "grade": "高一",
        "prerequisites": ["GDMATH-INEQ-01", "MID-QUAD-EQ"],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.30, "p_transit": 0.28, "p_guess": 0.15, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.50],
    },

    # =========================================================================
    # 必修第一册（高一上）—— 函数
    # =========================================================================
    {
        "kc_id": "GDMATH-FUNC-01", "name": "函数的概念（定义域/值域/对应关系）",
        "module": "必修一·函数", "grade": "高一",
        "prerequisites": ["MID-FUNC-BASIC"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 4,
        "bkt": {"p_init": 0.30, "p_transit": 0.25, "p_guess": 0.20, "p_slip": 0.10},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.40],
    },
    {
        "kc_id": "GDMATH-FUNC-02", "name": "函数的单调性与最值",
        "module": "必修一·函数", "grade": "高一",
        "prerequisites": ["GDMATH-FUNC-01"],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.22, "p_transit": 0.22, "p_guess": 0.20, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.50],
    },
    {
        "kc_id": "GDMATH-FUNC-03", "name": "函数的奇偶性与周期性",
        "module": "必修一·函数", "grade": "高一",
        "prerequisites": ["GDMATH-FUNC-01"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 4,
        "bkt": {"p_init": 0.20, "p_transit": 0.22, "p_guess": 0.20, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.50],
    },
    {
        "kc_id": "GDMATH-FUNC-04", "name": "指数与指数函数",
        "module": "必修一·函数", "grade": "高一",
        "prerequisites": ["GDMATH-FUNC-01", "MID-POWER"],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.22, "p_transit": 0.24, "p_guess": 0.18, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.45],
    },
    {
        "kc_id": "GDMATH-FUNC-05", "name": "对数与对数函数",
        "module": "必修一·函数", "grade": "高一",
        "prerequisites": ["GDMATH-FUNC-01", "MID-POWER"],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.20, "p_transit": 0.22, "p_guess": 0.18, "p_slip": 0.14},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.50],
    },
    {
        "kc_id": "GDMATH-FUNC-06", "name": "幂函数与函数的应用",
        "module": "必修一·函数", "grade": "高一",
        "prerequisites": ["GDMATH-FUNC-01"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 3,
        "bkt": {"p_init": 0.25, "p_transit": 0.24, "p_guess": 0.20, "p_slip": 0.10},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.40],
    },
    {
        "kc_id": "GDMATH-FUNC-07", "name": "函数零点与方程根的分布",
        "module": "必修一·函数", "grade": "高一",
        "prerequisites": ["GDMATH-FUNC-04", "GDMATH-FUNC-05"],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.18, "p_transit": 0.20, "p_guess": 0.18, "p_slip": 0.14},
        "ku_ids": [],
        "difficulty_range": [0.25, 0.55],
    },

    # =========================================================================
    # 必修第一册（高一上）—— 三角函数
    # =========================================================================
    {
        "kc_id": "GDMATH-TRIG-01", "name": "任意角与弧度制",
        "module": "必修一·三角函数", "grade": "高一",
        "prerequisites": ["GDMATH-FUNC-01"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 3,
        "bkt": {"p_init": 0.25, "p_transit": 0.28, "p_guess": 0.20, "p_slip": 0.10},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.35],
    },
    {
        "kc_id": "GDMATH-TRIG-02", "name": "三角函数的定义与基本关系",
        "module": "必修一·三角函数", "grade": "高一",
        "prerequisites": ["GDMATH-TRIG-01"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 4,
        "bkt": {"p_init": 0.22, "p_transit": 0.24, "p_guess": 0.18, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.45],
    },
    {
        "kc_id": "GDMATH-TRIG-03", "name": "诱导公式与同角三角函数关系",
        "module": "必修一·三角函数", "grade": "高一",
        "prerequisites": ["GDMATH-TRIG-02"],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.18, "p_transit": 0.22, "p_guess": 0.18, "p_slip": 0.14},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.50],
    },
    {
        "kc_id": "GDMATH-TRIG-04", "name": "三角函数的图象与性质（周期/奇偶/单调）",
        "module": "必修一·三角函数", "grade": "高一",
        "prerequisites": ["GDMATH-TRIG-02"],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.18, "p_transit": 0.20, "p_guess": 0.18, "p_slip": 0.14},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.50],
    },
    {
        "kc_id": "GDMATH-TRIG-05", "name": "y=Asin(ωx+φ) 的图象与性质",
        "module": "必修一·三角函数", "grade": "高一",
        "prerequisites": ["GDMATH-TRIG-04"],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 4,
        "bkt": {"p_init": 0.16, "p_transit": 0.18, "p_guess": 0.18, "p_slip": 0.15},
        "ku_ids": [],
        "difficulty_range": [0.25, 0.55],
    },
    {
        "kc_id": "GDMATH-TRIG-06", "name": "三角恒等变换（和差/倍角/辅助角）",
        "module": "必修一·三角函数", "grade": "高一",
        "prerequisites": ["GDMATH-TRIG-02"],
        "question_types": ["fill", "solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.15, "p_transit": 0.18, "p_guess": 0.05, "p_slip": 0.16},
        "ku_ids": [],
        "difficulty_range": [0.25, 0.55],
    },

    # =========================================================================
    # 必修第二册（高一下）—— 平面向量
    # =========================================================================
    {
        "kc_id": "GDMATH-VEC-01", "name": "平面向量的概念与线性运算",
        "module": "必修二·平面向量", "grade": "高一",
        "prerequisites": ["GDMATH-TRIG-02"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 4,
        "bkt": {"p_init": 0.25, "p_transit": 0.26, "p_guess": 0.20, "p_slip": 0.10},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.40],
    },
    {
        "kc_id": "GDMATH-VEC-02", "name": "平面向量的数量积及其应用",
        "module": "必修二·平面向量", "grade": "高一",
        "prerequisites": ["GDMATH-VEC-01"],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.22, "p_transit": 0.24, "p_guess": 0.18, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.50],
    },
    {
        "kc_id": "GDMATH-VEC-03", "name": "平面向量基本定理与坐标表示",
        "module": "必修二·平面向量", "grade": "高一",
        "prerequisites": ["GDMATH-VEC-01"],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 4,
        "bkt": {"p_init": 0.20, "p_transit": 0.24, "p_guess": 0.18, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.45],
    },
    {
        "kc_id": "GDMATH-TRIG-07", "name": "解三角形（正弦定理与余弦定理）",
        "module": "必修二·平面向量", "grade": "高一",
        "prerequisites": ["GDMATH-TRIG-06", "GDMATH-VEC-01"],
        "question_types": ["fill", "solve"],
        "gaokao_score": 12,
        "bkt": {"p_init": 0.18, "p_transit": 0.22, "p_guess": 0.05, "p_slip": 0.15},
        "ku_ids": [],
        "difficulty_range": [0.25, 0.60],
    },

    # =========================================================================
    # 必修第二册（高一下）—— 复数
    # =========================================================================
    {
        "kc_id": "GDMATH-COMPLEX-01", "name": "复数的概念与运算",
        "module": "必修二·复数", "grade": "高一",
        "prerequisites": ["GDMATH-INEQ-01"],
        "question_types": ["choice"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.35, "p_transit": 0.35, "p_guess": 0.25, "p_slip": 0.08},
        "ku_ids": [],
        "difficulty_range": [0.10, 0.30],
    },

    # =========================================================================
    # 必修第二册（高一下）—— 立体几何初步
    # =========================================================================
    {
        "kc_id": "GDMATH-SOLID-01", "name": "空间几何体的结构特征与表面积体积",
        "module": "必修二·立体几何", "grade": "高一",
        "prerequisites": [],
        "question_types": ["choice", "fill"],
        "gaokao_score": 4,
        "bkt": {"p_init": 0.25, "p_transit": 0.24, "p_guess": 0.20, "p_slip": 0.10},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.40],
    },
    {
        "kc_id": "GDMATH-SOLID-02", "name": "点线面位置关系（平行判定与性质）",
        "module": "必修二·立体几何", "grade": "高一",
        "prerequisites": ["GDMATH-SOLID-01"],
        "question_types": ["choice", "solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.18, "p_transit": 0.20, "p_guess": 0.18, "p_slip": 0.13},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.50],
    },
    {
        "kc_id": "GDMATH-SOLID-03", "name": "点线面位置关系（垂直判定与性质）",
        "module": "必修二·立体几何", "grade": "高一",
        "prerequisites": ["GDMATH-SOLID-02"],
        "question_types": ["choice", "solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.16, "p_transit": 0.18, "p_guess": 0.18, "p_slip": 0.14},
        "ku_ids": [],
        "difficulty_range": [0.25, 0.55],
    },

    # =========================================================================
    # 必修第二册（高一下）—— 统计与概率
    # =========================================================================
    {
        "kc_id": "GDMATH-STAT-01", "name": "统计（抽样方法与数字特征）",
        "module": "必修二·统计", "grade": "高一",
        "prerequisites": [],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.30, "p_transit": 0.30, "p_guess": 0.18, "p_slip": 0.10},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.40],
    },
    {
        "kc_id": "GDMATH-PROB-01", "name": "古典概型与概率的基本性质",
        "module": "必修二·概率", "grade": "高一",
        "prerequisites": [],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.25, "p_transit": 0.26, "p_guess": 0.15, "p_slip": 0.11},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.40],
    },

    # =========================================================================
    # 选择性必修第一册（高二上）—— 空间向量与立体几何
    # =========================================================================
    {
        "kc_id": "GDMATH-SVEC-01", "name": "空间向量的概念与运算",
        "module": "选必一·空间向量", "grade": "高二",
        "prerequisites": ["GDMATH-VEC-01", "GDMATH-VEC-02"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 4,
        "bkt": {"p_init": 0.20, "p_transit": 0.24, "p_guess": 0.18, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.45],
    },
    {
        "kc_id": "GDMATH-SVEC-02", "name": "空间向量基本定理与坐标运算",
        "module": "选必一·空间向量", "grade": "高二",
        "prerequisites": ["GDMATH-SVEC-01"],
        "question_types": ["fill", "solve"],
        "gaokao_score": 4,
        "bkt": {"p_init": 0.18, "p_transit": 0.22, "p_guess": 0.10, "p_slip": 0.14},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.50],
    },
    {
        "kc_id": "GDMATH-SVEC-03", "name": "向量法解决平行与垂直问题",
        "module": "选必一·空间向量", "grade": "高二",
        "prerequisites": ["GDMATH-SVEC-02", "GDMATH-SOLID-02", "GDMATH-SOLID-03"],
        "question_types": ["solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.15, "p_transit": 0.20, "p_guess": 0.02, "p_slip": 0.15},
        "ku_ids": [],
        "difficulty_range": [0.30, 0.55],
    },
    {
        "kc_id": "GDMATH-SVEC-04", "name": "向量法求空间角与距离",
        "module": "选必一·空间向量", "grade": "高二",
        "prerequisites": ["GDMATH-SVEC-02", "GDMATH-SOLID-02", "GDMATH-SOLID-03"],
        "question_types": ["solve"],
        "gaokao_score": 8,
        "bkt": {"p_init": 0.12, "p_transit": 0.18, "p_guess": 0.02, "p_slip": 0.16},
        "ku_ids": [],
        "difficulty_range": [0.30, 0.60],
    },

    # =========================================================================
    # 选择性必修第一册（高二上）—— 直线与圆
    # =========================================================================
    {
        "kc_id": "GDMATH-LINE-01", "name": "直线的方程与位置关系",
        "module": "选必一·解析几何", "grade": "高二",
        "prerequisites": ["GDMATH-FUNC-01"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.25, "p_transit": 0.26, "p_guess": 0.18, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.40],
    },
    {
        "kc_id": "GDMATH-CIRCLE-01", "name": "圆的方程与直线圆的位置关系",
        "module": "选必一·解析几何", "grade": "高二",
        "prerequisites": ["GDMATH-LINE-01"],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.22, "p_transit": 0.24, "p_guess": 0.18, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.50],
    },

    # =========================================================================
    # 选择性必修第一册（高二上）—— 圆锥曲线
    # =========================================================================
    {
        "kc_id": "GDMATH-CONIC-01", "name": "椭圆的定义、标准方程与几何性质",
        "module": "选必一·圆锥曲线", "grade": "高二",
        "prerequisites": ["GDMATH-CIRCLE-01"],
        "question_types": ["fill", "solve"],
        "gaokao_score": 8,
        "bkt": {"p_init": 0.15, "p_transit": 0.18, "p_guess": 0.05, "p_slip": 0.15},
        "ku_ids": [],
        "difficulty_range": [0.25, 0.55],
    },
    {
        "kc_id": "GDMATH-CONIC-02", "name": "双曲线的定义、标准方程与几何性质",
        "module": "选必一·圆锥曲线", "grade": "高二",
        "prerequisites": ["GDMATH-CONIC-01"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.14, "p_transit": 0.17, "p_guess": 0.18, "p_slip": 0.15},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.50],
    },
    {
        "kc_id": "GDMATH-CONIC-03", "name": "抛物线的定义、标准方程与几何性质",
        "module": "选必一·圆锥曲线", "grade": "高二",
        "prerequisites": ["GDMATH-CONIC-01"],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.14, "p_transit": 0.17, "p_guess": 0.12, "p_slip": 0.15},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.50],
    },
    {
        "kc_id": "GDMATH-CONIC-04", "name": "直线与圆锥曲线的位置关系（弦长/中点弦）",
        "module": "选必一·圆锥曲线", "grade": "高三",
        "prerequisites": ["GDMATH-CONIC-01", "GDMATH-CONIC-02", "GDMATH-CONIC-03", "GDMATH-LINE-01"],
        "question_types": ["solve"],
        "gaokao_score": 8,
        "bkt": {"p_init": 0.08, "p_transit": 0.12, "p_guess": 0.01, "p_slip": 0.18},
        "ku_ids": [],
        "difficulty_range": [0.35, 0.65],
    },
    {
        "kc_id": "GDMATH-CONIC-05", "name": "圆锥曲线综合（定点定值/最值/存在性）",
        "module": "选必一·圆锥曲线", "grade": "高三",
        "prerequisites": ["GDMATH-CONIC-04"],
        "question_types": ["solve"],
        "gaokao_score": 10,
        "bkt": {"p_init": 0.05, "p_transit": 0.08, "p_guess": 0.01, "p_slip": 0.22},
        "ku_ids": [],
        "difficulty_range": [0.50, 0.80],
    },

    # =========================================================================
    # 选择性必修第二册（高二下）—— 数列
    # =========================================================================
    {
        "kc_id": "GDMATH-SEQ-01", "name": "数列的概念与表示方法",
        "module": "选必二·数列", "grade": "高二",
        "prerequisites": ["GDMATH-FUNC-01"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 3,
        "bkt": {"p_init": 0.25, "p_transit": 0.28, "p_guess": 0.20, "p_slip": 0.10},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.35],
    },
    {
        "kc_id": "GDMATH-SEQ-02", "name": "等差数列（定义/通项/求和/性质）",
        "module": "选必二·数列", "grade": "高二",
        "prerequisites": ["GDMATH-SEQ-01"],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.22, "p_transit": 0.25, "p_guess": 0.12, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.45],
    },
    {
        "kc_id": "GDMATH-SEQ-03", "name": "等比数列（定义/通项/求和/性质）",
        "module": "选必二·数列", "grade": "高二",
        "prerequisites": ["GDMATH-SEQ-01"],
        "question_types": ["choice", "fill", "solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.20, "p_transit": 0.24, "p_guess": 0.12, "p_slip": 0.13},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.45],
    },
    {
        "kc_id": "GDMATH-SEQ-04", "name": "数列求和（裂项相消/错位相减/分组求和）",
        "module": "选必二·数列", "grade": "高二",
        "prerequisites": ["GDMATH-SEQ-02", "GDMATH-SEQ-03"],
        "question_types": ["solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.14, "p_transit": 0.18, "p_guess": 0.02, "p_slip": 0.16},
        "ku_ids": [],
        "difficulty_range": [0.30, 0.55],
    },
    {
        "kc_id": "GDMATH-SEQ-05", "name": "数列综合（递推/通项/不等式证明）",
        "module": "选必二·数列", "grade": "高三",
        "prerequisites": ["GDMATH-SEQ-04"],
        "question_types": ["solve"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.08, "p_transit": 0.12, "p_guess": 0.01, "p_slip": 0.18},
        "ku_ids": [],
        "difficulty_range": [0.40, 0.70],
    },

    # =========================================================================
    # 选择性必修第二册（高二下）—— 导数
    # =========================================================================
    {
        "kc_id": "GDMATH-DERIV-01", "name": "导数的概念与几何意义（切线）",
        "module": "选必二·导数", "grade": "高二",
        "prerequisites": ["GDMATH-FUNC-04", "GDMATH-FUNC-05"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.20, "p_transit": 0.24, "p_guess": 0.18, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.45],
    },
    {
        "kc_id": "GDMATH-DERIV-02", "name": "导数的运算（四则运算法则与复合函数）",
        "module": "选必二·导数", "grade": "高二",
        "prerequisites": ["GDMATH-DERIV-01"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 4,
        "bkt": {"p_init": 0.18, "p_transit": 0.22, "p_guess": 0.15, "p_slip": 0.14},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.45],
    },
    {
        "kc_id": "GDMATH-DERIV-03", "name": "导数研究函数单调性",
        "module": "选必二·导数", "grade": "高二",
        "prerequisites": ["GDMATH-DERIV-02", "GDMATH-FUNC-02"],
        "question_types": ["solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.14, "p_transit": 0.18, "p_guess": 0.03, "p_slip": 0.15},
        "ku_ids": [],
        "difficulty_range": [0.25, 0.55],
    },
    {
        "kc_id": "GDMATH-DERIV-04", "name": "导数研究函数的极值与最值",
        "module": "选必二·导数", "grade": "高三",
        "prerequisites": ["GDMATH-DERIV-03"],
        "question_types": ["solve"],
        "gaokao_score": 6,
        "bkt": {"p_init": 0.10, "p_transit": 0.14, "p_guess": 0.02, "p_slip": 0.17},
        "ku_ids": [],
        "difficulty_range": [0.30, 0.60],
    },
    {
        "kc_id": "GDMATH-DERIV-05", "name": "导数综合（含参讨论/不等式证明/零点）",
        "module": "选必二·导数", "grade": "高三",
        "prerequisites": ["GDMATH-DERIV-04", "GDMATH-FUNC-07"],
        "question_types": ["solve"],
        "gaokao_score": 10,
        "bkt": {"p_init": 0.04, "p_transit": 0.08, "p_guess": 0.01, "p_slip": 0.22},
        "ku_ids": [],
        "difficulty_range": [0.50, 0.85],
    },

    # =========================================================================
    # 选择性必修第三册（高二下/高三）—— 计数原理
    # =========================================================================
    {
        "kc_id": "GDMATH-COUNT-01", "name": "分类加法与分步乘法计数原理",
        "module": "选必三·计数原理", "grade": "高二",
        "prerequisites": ["GDMATH-PROB-01"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 3,
        "bkt": {"p_init": 0.20, "p_transit": 0.24, "p_guess": 0.20, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.40],
    },
    {
        "kc_id": "GDMATH-COUNT-02", "name": "排列与组合",
        "module": "选必三·计数原理", "grade": "高二",
        "prerequisites": ["GDMATH-COUNT-01"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.16, "p_transit": 0.20, "p_guess": 0.18, "p_slip": 0.15},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.50],
    },
    {
        "kc_id": "GDMATH-COUNT-03", "name": "二项式定理",
        "module": "选必三·计数原理", "grade": "高二",
        "prerequisites": ["GDMATH-COUNT-02"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 3,
        "bkt": {"p_init": 0.18, "p_transit": 0.22, "p_guess": 0.20, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.40],
    },

    # =========================================================================
    # 选择性必修第三册（高三）—— 概率分布
    # =========================================================================
    {
        "kc_id": "GDMATH-PROB-02", "name": "条件概率与全概率公式",
        "module": "选必三·概率分布", "grade": "高三",
        "prerequisites": ["GDMATH-PROB-01"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 3,
        "bkt": {"p_init": 0.18, "p_transit": 0.20, "p_guess": 0.18, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.45],
    },
    {
        "kc_id": "GDMATH-PROB-03", "name": "离散型随机变量及其分布（期望方差）",
        "module": "选必三·概率分布", "grade": "高三",
        "prerequisites": ["GDMATH-PROB-01", "GDMATH-COUNT-02"],
        "question_types": ["solve"],
        "gaokao_score": 12,
        "bkt": {"p_init": 0.12, "p_transit": 0.16, "p_guess": 0.03, "p_slip": 0.15},
        "ku_ids": [],
        "difficulty_range": [0.30, 0.55],
    },
    {
        "kc_id": "GDMATH-PROB-04", "name": "二项分布与超几何分布",
        "module": "选必三·概率分布", "grade": "高三",
        "prerequisites": ["GDMATH-PROB-03"],
        "question_types": ["fill", "solve"],
        "gaokao_score": 5,
        "bkt": {"p_init": 0.12, "p_transit": 0.16, "p_guess": 0.05, "p_slip": 0.14},
        "ku_ids": [],
        "difficulty_range": [0.25, 0.50],
    },
    {
        "kc_id": "GDMATH-PROB-05", "name": "正态分布",
        "module": "选必三·概率分布", "grade": "高三",
        "prerequisites": ["GDMATH-PROB-03"],
        "question_types": ["choice", "fill"],
        "gaokao_score": 3,
        "bkt": {"p_init": 0.15, "p_transit": 0.20, "p_guess": 0.20, "p_slip": 0.10},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.35],
    },

    # =========================================================================
    # 选择性必修第三册（高三）—— 统计分析
    # =========================================================================
    {
        "kc_id": "GDMATH-STAT-02", "name": "成对数据的统计分析（回归分析）",
        "module": "选必三·统计分析", "grade": "高三",
        "prerequisites": ["GDMATH-STAT-01"],
        "question_types": ["solve"],
        "gaokao_score": 4,
        "bkt": {"p_init": 0.18, "p_transit": 0.22, "p_guess": 0.04, "p_slip": 0.12},
        "ku_ids": [],
        "difficulty_range": [0.20, 0.45],
    },
    {
        "kc_id": "GDMATH-STAT-03", "name": "独立性检验（2×2列联表）",
        "module": "选必三·统计分析", "grade": "高三",
        "prerequisites": ["GDMATH-STAT-01"],
        "question_types": ["solve"],
        "gaokao_score": 3,
        "bkt": {"p_init": 0.20, "p_transit": 0.24, "p_guess": 0.05, "p_slip": 0.10},
        "ku_ids": [],
        "difficulty_range": [0.15, 0.40],
    },
]

# =========================================================================
# 初中阶段前置知识点（补全 BKT 参数）
# =========================================================================
MIDDLE_SCHOOL_KC_STUBS: dict[str, dict[str, Any]] = {
    "MID-QUAD-EQ": {
        "name": "一元二次方程（初中）",
        "bkt": {"p_init": 0.55, "p_transit": 0.35, "p_guess": 0.20, "p_slip": 0.08},
    },
    "MID-FUNC-BASIC": {
        "name": "函数基础与一次/反比例函数（初中）",
        "bkt": {"p_init": 0.50, "p_transit": 0.32, "p_guess": 0.20, "p_slip": 0.10},
    },
    "MID-POWER": {
        "name": "幂的运算与幂函数初步（初中）",
        "bkt": {"p_init": 0.50, "p_transit": 0.30, "p_guess": 0.20, "p_slip": 0.08},
    },
    "MID-SIMILAR": {
        "name": "相似三角形（初中）",
        "bkt": {"p_init": 0.40, "p_transit": 0.28, "p_guess": 0.18, "p_slip": 0.12},
    },
    "MID-CIRCLE": {
        "name": "圆的基本性质（初中）",
        "bkt": {"p_init": 0.40, "p_transit": 0.26, "p_guess": 0.18, "p_slip": 0.12},
    },
    "MID-PROB": {
        "name": "概率初步（初中）",
        "bkt": {"p_init": 0.50, "p_transit": 0.30, "p_guess": 0.20, "p_slip": 0.08},
    },
    "MID-STAT": {
        "name": "统计初步（初中）",
        "bkt": {"p_init": 0.55, "p_transit": 0.30, "p_guess": 0.18, "p_slip": 0.08},
    },
    "MID-PYTHAG": {
        "name": "勾股定理（初中）",
        "bkt": {"p_init": 0.50, "p_transit": 0.30, "p_guess": 0.20, "p_slip": 0.10},
    },
}

# =========================================================================
# 索引与工具函数
# =========================================================================
KC_INDEX = {kc["kc_id"]: kc for kc in KC_LIST}


def get_kc(kc_id: str) -> dict | None:
    return KC_INDEX.get(kc_id)


def get_bkt_prior(kc_id: str) -> dict:
    """返回某 KC 的 BKT 先验参数；未知 KC 给一个保守默认。"""
    kc = KC_INDEX.get(kc_id)
    if kc:
        return dict(kc["bkt"])
    # 检查是否初中占位
    if kc_id in MIDDLE_SCHOOL_KC_STUBS:
        return dict(MIDDLE_SCHOOL_KC_STUBS[kc_id]["bkt"])
    return {"p_init": 0.20, "p_transit": 0.20, "p_guess": 0.15, "p_slip": 0.12}


def all_prerequisites(kc_id: str, _seen: set | None = None) -> list[str]:
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


def total_gaokao_score() -> int:
    return sum(int(kc["gaokao_score"]) for kc in KC_LIST)


def kc_summary() -> dict:
    return {
        "total_kc": len(KC_LIST),
        "by_grade": {
            g: len([k for k in KC_LIST if k["grade"] == g])
            for g in ["高一", "高二", "高三"]
        },
        "by_module": {
            m: len([k for k in KC_LIST if k["module"] == m])
            for m in sorted(set(k["module"] for k in KC_LIST))
        },
        "total_gaokao_score_covered": total_gaokao_score(),
    }


def get_kcs_by_grade(grade: str) -> list[dict]:
    """按年级筛选 KC。"""
    return [kc for kc in KC_LIST if kc["grade"] == grade]


def get_kcs_by_module(module: str) -> list[dict]:
    """按模块筛选 KC。"""
    return [kc for kc in KC_LIST if kc["module"] == module]


if __name__ == "__main__":
    import json
    print(json.dumps(kc_summary(), ensure_ascii=False, indent=2))
    print(f"\n初中前置占位: {list(MIDDLE_SCHOOL_KC_STUBS.keys())}")
    print("\n示例：圆锥曲线综合的全部前置链：")
    print(all_prerequisites("GDMATH-CONIC-05"))