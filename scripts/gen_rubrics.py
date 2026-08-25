"""Phase 4: Create rubrics for qualitative KCs and seed gate.rubric table."""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.guangdong_math_kc_v2 import KC_INDEX

# Rubric for each qualitative KC
# Dimensions: correctness, completeness, reasoning, notation
RUBRICS = {
    # 解三角形
    "GDMATH-TRIG-07": {
        "kc_id": "GDMATH-TRIG-07",
        "dimensions": [
            {"name": "正余弦定理选择", "criterion": "能根据已知条件正确选择正弦定理或余弦定理", "weight": 0.3},
            {"name": "计算正确性", "criterion": "代入计算准确，无符号/数值错误", "weight": 0.3},
            {"name": "分类讨论完整", "criterion": "多解情形（如SSA）能完整讨论不遗漏", "weight": 0.2},
            {"name": "表达规范性", "criterion": "步骤清晰，公式引用正确，单位一致", "weight": 0.2},
        ],
        "author": "system",
    },
    # 立体几何平行证明
    "GDMATH-SOLID-02": {
        "kc_id": "GDMATH-SOLID-02",
        "dimensions": [
            {"name": "判定定理选择", "criterion": "能正确选择线面平行/面面平行的判定定理", "weight": 0.3},
            {"name": "推理逻辑链", "criterion": "从已知条件到结论的推理链条完整且正确", "weight": 0.3},
            {"name": "辅助线构造", "criterion": "辅助线/辅助面构造合理，帮助建立联系", "weight": 0.2},
            {"name": "表达规范性", "criterion": "使用标准数学符号，论述严谨", "weight": 0.2},
        ],
        "author": "system",
    },
    # 立体几何垂直证明
    "GDMATH-SOLID-03": {
        "kc_id": "GDMATH-SOLID-03",
        "dimensions": [
            {"name": "垂直关系判定", "criterion": "正确识别线线/线面/面面垂直判定条件", "weight": 0.3},
            {"name": "推理逻辑链", "criterion": "从条件到结论的推理链完整", "weight": 0.3},
            {"name": "辅助线构造", "criterion": "辅助线/面构造合理有效", "weight": 0.2},
            {"name": "表达规范性", "criterion": "使用标准符号，逻辑严谨", "weight": 0.2},
        ],
        "author": "system",
    },
    # 空间向量法求角与距离
    "GDMATH-SVEC-04": {
        "kc_id": "GDMATH-SVEC-04",
        "dimensions": [
            {"name": "坐标系建立", "criterion": "坐标系建立合理，能简化计算", "weight": 0.2},
            {"name": "向量表示", "criterion": "点和方向向量表示正确", "weight": 0.2},
            {"name": "法向量求解", "criterion": "法向量计算正确", "weight": 0.2},
            {"name": "公式应用", "criterion": "角度/距离公式选择正确，代入无误", "weight": 0.2},
            {"name": "计算正确性", "criterion": "数值计算准确，结果合理", "weight": 0.2},
        ],
        "author": "system",
    },
    # 空间向量平行垂直
    "GDMATH-SVEC-03": {
        "kc_id": "GDMATH-SVEC-03",
        "dimensions": [
            {"name": "坐标系建立", "criterion": "坐标系建立合理", "weight": 0.25},
            {"name": "方向向量/法向量", "criterion": "向量表示和计算正确", "weight": 0.3},
            {"name": "判定条件", "criterion": "平行/垂直的向量判定条件运用正确", "weight": 0.25},
            {"name": "表达规范性", "criterion": "论述清晰，推理严谨", "weight": 0.2},
        ],
        "author": "system",
    },
    # 圆锥曲线综合（压轴）
    "GDMATH-CONIC-04": {
        "kc_id": "GDMATH-CONIC-04",
        "dimensions": [
            {"name": "方程联立", "criterion": "直线与曲线方程联立正确", "weight": 0.2},
            {"name": "判别式与韦达定理", "criterion": "判别式分析和韦达定理应用正确", "weight": 0.25},
            {"name": "代数运算", "criterion": "代数变形和化简准确", "weight": 0.25},
            {"name": "弦长公式", "criterion": "弦长公式/中点弦公式应用正确", "weight": 0.15},
            {"name": "结论完整性", "criterion": "分类讨论完整，结论不遗漏", "weight": 0.15},
        ],
        "author": "system",
    },
    "GDMATH-CONIC-05": {
        "kc_id": "GDMATH-CONIC-05",
        "dimensions": [
            {"name": "策略选择", "criterion": "定点/定值/最值等问题的解题策略正确", "weight": 0.2},
            {"name": "方程联立", "criterion": "联立方程正确", "weight": 0.15},
            {"name": "代数运算", "criterion": "复杂代数变形准确", "weight": 0.3},
            {"name": "分类讨论", "criterion": "参数讨论完整，不遗漏特殊情况", "weight": 0.2},
            {"name": "结论验证", "criterion": "结论有验证或合理性检查", "weight": 0.15},
        ],
        "author": "system",
    },
    # 数列综合
    "GDMATH-SEQ-04": {
        "kc_id": "GDMATH-SEQ-04",
        "dimensions": [
            {"name": "求和方法选择", "criterion": "能根据数列特征选择正确的求和方法", "weight": 0.25},
            {"name": "裂项/错位相减", "criterion": "裂项相消或错位相减的变形正确", "weight": 0.3},
            {"name": "计算正确性", "criterion": "代数运算和化简准确", "weight": 0.25},
            {"name": "表达规范性", "criterion": "步骤清晰，符号使用正确", "weight": 0.2},
        ],
        "author": "system",
    },
    "GDMATH-SEQ-05": {
        "kc_id": "GDMATH-SEQ-05",
        "dimensions": [
            {"name": "递推关系处理", "criterion": "递推公式变形正确", "weight": 0.25},
            {"name": "通项求解", "criterion": "通项公式推导正确", "weight": 0.25},
            {"name": "不等式证明", "criterion": "放缩/数学归纳法等证明方法运用正确", "weight": 0.3},
            {"name": "整体策略", "criterion": "解题思路清晰，方法选择合理", "weight": 0.2},
        ],
        "author": "system",
    },
    # 导数综合
    "GDMATH-DERIV-03": {
        "kc_id": "GDMATH-DERIV-03",
        "dimensions": [
            {"name": "求导正确性", "criterion": "导函数计算正确", "weight": 0.25},
            {"name": "单调性分析", "criterion": "导函数符号判断正确，单调区间完整", "weight": 0.3},
            {"name": "参数讨论", "criterion": "含参时分类讨论完整", "weight": 0.25},
            {"name": "表达规范性", "criterion": "推导过程清晰，结论明确", "weight": 0.2},
        ],
        "author": "system",
    },
    "GDMATH-DERIV-05": {
        "kc_id": "GDMATH-DERIV-05",
        "dimensions": [
            {"name": "求导与变形", "criterion": "导函数计算和代数变形正确", "weight": 0.2},
            {"name": "函数性态分析", "criterion": "单调性/极值/最值分析完整", "weight": 0.2},
            {"name": "不等式构造", "criterion": "不等式证明的构造函数/放缩方法正确", "weight": 0.25},
            {"name": "含参讨论", "criterion": "参数讨论完整严谨", "weight": 0.2},
            {"name": "逻辑严密性", "criterion": "推理链条完整，无跳跃", "weight": 0.15},
        ],
        "author": "system",
    },
    # 概率分布解答
    "GDMATH-PROB-03": {
        "kc_id": "GDMATH-PROB-03",
        "dimensions": [
            {"name": "分布列构建", "criterion": "随机变量取值和对应概率正确", "weight": 0.3},
            {"name": "期望计算", "criterion": "期望公式代入正确，计算准确", "weight": 0.25},
            {"name": "方差计算", "criterion": "方差公式应用正确", "weight": 0.2},
            {"name": "实际问题建模", "criterion": "能正确将实际问题转化为概率模型", "weight": 0.25},
        ],
        "author": "system",
    },
    # 统计分析
    "GDMATH-STAT-02": {
        "kc_id": "GDMATH-STAT-02",
        "dimensions": [
            {"name": "模型选择", "criterion": "线性/非线性回归模型选择合理", "weight": 0.25},
            {"name": "计算正确性", "criterion": "回归系数和相关性计算正确", "weight": 0.3},
            {"name": "结果解释", "criterion": "对回归结果的实际含义解释正确", "weight": 0.25},
            {"name": "残差分析", "criterion": "残差分析与模型检验完整", "weight": 0.2},
        ],
        "author": "system",
    },
    "GDMATH-STAT-03": {
        "kc_id": "GDMATH-STAT-03",
        "dimensions": [
            {"name": "列联表构建", "criterion": "2×2列联表构建正确", "weight": 0.25},
            {"name": "期望频数计算", "criterion": "独立假设下的期望频数计算正确", "weight": 0.25},
            {"name": "χ²统计量", "criterion": "χ²统计量计算正确", "weight": 0.25},
            {"name": "结论推断", "criterion": "临界值比较和结论推断正确", "weight": 0.25},
        ],
        "author": "system",
    },
}

def main():
    # 输出 rubric JSON（供 gate_store 导入）
    rubrics = []
    for kc_id, rubric in sorted(RUBRICS.items()):
        kc = KC_INDEX.get(kc_id)
        rubric['kc_name'] = kc['name'] if kc else kc_id
        rubrics.append(rubric)
    
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'seed_rubrics.json')
    with open(out, 'w') as f:
        json.dump(rubrics, f, ensure_ascii=False, indent=2)
    
    print('Rubrics: {} KC'.format(len(rubrics)))
    for r in rubrics:
        print('  {} - {} ({} dimensions)'.format(r['kc_id'], r.get('kc_name',''), len(r['dimensions'])))
    print('Written: {}'.format(out))

if __name__ == '__main__':
    main()