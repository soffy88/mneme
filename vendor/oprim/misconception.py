"""L3 · 误解诊断骨架。纯函数 + 可扩展登记表。

评价的诊断层：答错不只知道"错了"，要知道"为什么错"（挂误解 ID）→ 触发概念重建微课，
而非同类题再刷（物理 FCI 的干扰项设计哲学）。

**机制**：选择题干扰项 → 误解 ID 的精确映射（`distractor_map`，内容由教研逐题填）；
无映射时按 KU 名关键词退回候选误解（启发式，弱）。主观题由 verify_step 错误模式聚类反推（待接）。
本模块提供**结构 + 登记表 + 查询接口**，seed 了几条高频误解，内容按流量滚动补齐。
"""

from __future__ import annotations

from typing import Optional

# 误解登记表：{id, subject, label(误解陈述), remediation(重建方向), keywords(KU 名启发式匹配)}
# distractor_map: {(ku_id, 干扰项字母): misconception_id} —— 精确映射，教研逐题填。
MISCONCEPTIONS: list[dict] = [
    {
        "id": "MATH-NEG-SIGN",
        "subject": "math",
        "label": "负号/相反数处理错误（如 -(-a) 当作 -a）",
        "remediation": "数轴对称 + 相反数定义对比案例",
        "keywords": ["负数", "相反数", "绝对值"],
    },
    {
        "id": "MATH-FRAC-OP",
        "subject": "math",
        "label": "分数运算：分母直接相加/通分遗漏",
        "remediation": "面积模型 + 通分必要性冲突案例",
        "keywords": ["分数", "通分", "分式"],
    },
    {
        "id": "MATH-VAR-AS-LABEL",
        "subject": "math",
        "label": "字母当标签而非变量（如 3a 读作‘3 个苹果’）",
        "remediation": "变量取值表 + 代入检验",
        "keywords": ["字母表示", "代数式", "方程"],
    },
    {
        "id": "MATH-FUNC-CONCEPT",
        "subject": "math",
        "label": "函数概念：一对多也当函数 / 混淆自变量因变量",
        "remediation": "映射图 + 反例（一对多非函数）",
        "keywords": ["函数", "映射", "定义域"],
    },
    {
        "id": "PHYS-FORCE-MOTION",
        "subject": "physics",
        "label": "力与运动：有力才有速度（亚里士多德直觉）",
        "remediation": "惯性演示 + 匀速无合力冲突案例",
        "keywords": ["力", "运动", "惯性", "牛顿第一"],
    },
    {
        "id": "PHYS-CIRCUIT",
        "subject": "physics",
        "label": "电路：电流被用光 / 电池恒流源误解",
        "remediation": "回路守恒 + 串并联电流对比",
        "keywords": ["电路", "电流", "串联", "并联"],
    },
]
_BY_ID = {m["id"]: m for m in MISCONCEPTIONS}

# 精确映射（教研逐题填）：seed 空，接口就位
DISTRACTOR_MAP: dict[tuple[str, str], str] = {}


def diagnose_misconception(
    subject: str,
    ku_name: str,
    *,
    ku_id: Optional[str] = None,
    distractor: Optional[str] = None,
) -> Optional[dict]:
    """诊断误解：优先精确干扰项映射；否则按 KU 名关键词退回候选（弱，标注 heuristic）。

    返回 {id, label, remediation, precision: exact|heuristic} 或 None。
    """
    # 1) 精确：干扰项映射（内容就位后走这条）
    if ku_id and distractor:
        mid = DISTRACTOR_MAP.get((ku_id, distractor.strip().upper()))
        if mid and mid in _BY_ID:
            m = _BY_ID[mid]
            return {
                "id": m["id"],
                "label": m["label"],
                "remediation": m["remediation"],
                "precision": "exact",
            }
    # 2) 启发式：KU 名关键词匹配同科目误解
    name = ku_name or ""
    for m in MISCONCEPTIONS:
        if m["subject"] != subject:
            continue
        if any(kw in name for kw in m["keywords"]):
            return {
                "id": m["id"],
                "label": m["label"],
                "remediation": m["remediation"],
                "precision": "heuristic",
            }
    return None


__all__ = ["MISCONCEPTIONS", "DISTRACTOR_MAP", "diagnose_misconception"]
