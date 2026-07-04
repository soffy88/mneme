"""
国家数学课程标准对齐骨架 (Curriculum Standard Alignment)
=====================================================
依据：《义务教育数学课程标准（2022年版）》《普通高中数学课程标准（2017年版2020年修订）》。

用途：把产品内部知识单元（KU/KC）挂到国家课标条目上，形成纵向可串联的档案地基。
这是护城河数据的一部分——课标是全国统一的"骨架"，广东人教版是"皮"（版本差异走
KC→教材章节的另一张映射，不污染这里的课标编码）。

编码方案（一条一码、永不复用、永不改写）：
- 内容条目主编码  GB-MATH-<SEG>-[<STAGE>-]<DOMAIN>-<TOPIC>[-<UNIT>]
    SEG    : JY(义务教育) / GZ(高中)
    STAGE  : 高中用 BX(必修)/XBX(选择性必修)/XX(选修)；义教主题码已自带学段区分，不入编码
    DOMAIN : 领域   NA数与代数 GM图形与几何 SP统计与概率 PA综合与实践
    TOPIC  : 主题（2 字母，SEG 内唯一）
    UNIT   : 高中内容单元细目（可选）
- 核心素养标签    GB-MATH-CL-<SEG>-<CODE>[-<LEVEL>]   (CL=Core Literacy；LEVEL 仅高中 L1/L2/L3)

一条 KU 的对齐记录 = 1 个主编码（挂到能唯一定位的最细层级）+ 1–3 个素养标签
（默认值见 DEFAULT_LITERACY_BY_DOMAIN，人工微调）+ 高中的 target_level(L1/L2/L3，做成
同一 KU 的掌握度目标阈值，不拆 KU）。跨两个主题的 KU 应拆开，不要一码多挂。

主要来源：教育部义教/高中课标印发通知、课程教材研究所高中数学课标2017/2020修订版全文。
"""

from __future__ import annotations

from typing import Optional

# ── 内容条目节点：{code, seg, stage, domain, topic, name, kind} ──
# kind: domain(领域) / topic(主题) / unit(高中内容单元细目)
STD_NODES: list[dict] = [
    # ============ 义务教育 · 数与代数 NA ============
    {
        "code": "GB-MATH-JY-NA-SY",
        "seg": "JY",
        "stage": "小学",
        "domain": "NA",
        "topic": "SY",
        "name": "数与运算",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-JY-NA-SL",
        "seg": "JY",
        "stage": "小学",
        "domain": "NA",
        "topic": "SL",
        "name": "数量关系",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-JY-NA-SS",
        "seg": "JY",
        "stage": "初中",
        "domain": "NA",
        "topic": "SS",
        "name": "数与式",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-JY-NA-FB",
        "seg": "JY",
        "stage": "初中",
        "domain": "NA",
        "topic": "FB",
        "name": "方程与不等式",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-JY-NA-HS",
        "seg": "JY",
        "stage": "初中",
        "domain": "NA",
        "topic": "HS",
        "name": "函数",
        "kind": "topic",
    },
    # ============ 义务教育 · 图形与几何 GM ============
    {
        "code": "GB-MATH-JY-GM-RM",
        "seg": "JY",
        "stage": "小学",
        "domain": "GM",
        "topic": "RM",
        "name": "图形的认识与测量",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-JY-GM-PM",
        "seg": "JY",
        "stage": "小学",
        "domain": "GM",
        "topic": "PM",
        "name": "图形的位置与运动",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-JY-GM-PR",
        "seg": "JY",
        "stage": "初中",
        "domain": "GM",
        "topic": "PR",
        "name": "图形的性质",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-JY-GM-TR",
        "seg": "JY",
        "stage": "初中",
        "domain": "GM",
        "topic": "TR",
        "name": "图形的变化",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-JY-GM-CO",
        "seg": "JY",
        "stage": "初中",
        "domain": "GM",
        "topic": "CO",
        "name": "图形与坐标",
        "kind": "topic",
    },
    # ============ 义务教育 · 统计与概率 SP ============
    {
        "code": "GB-MATH-JY-SP-DC",
        "seg": "JY",
        "stage": "小学",
        "domain": "SP",
        "topic": "DC",
        "name": "数据分类",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-JY-SP-DE",
        "seg": "JY",
        "stage": "小学",
        "domain": "SP",
        "topic": "DE",
        "name": "数据的收集、整理与表达",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-JY-SP-RP",
        "seg": "JY",
        "stage": "小学",
        "domain": "SP",
        "topic": "RP",
        "name": "随机现象发生的可能性",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-JY-SP-SA",
        "seg": "JY",
        "stage": "初中",
        "domain": "SP",
        "topic": "SA",
        "name": "抽样与数据分析",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-JY-SP-EP",
        "seg": "JY",
        "stage": "初中",
        "domain": "SP",
        "topic": "EP",
        "name": "随机事件的概率",
        "kind": "topic",
    },
    # ============ 义务教育 · 综合与实践 PA ============
    {
        "code": "GB-MATH-JY-PA-TA",
        "seg": "JY",
        "stage": "义教",
        "domain": "PA",
        "topic": "TA",
        "name": "主题活动（含跨学科主题学习）",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-JY-PA-PL",
        "seg": "JY",
        "stage": "初中",
        "domain": "PA",
        "topic": "PL",
        "name": "项目学习",
        "kind": "topic",
    },
    # ============ 高中 · 必修 BX ============
    {
        "code": "GB-MATH-GZ-BX-PREP",
        "seg": "GZ",
        "stage": "BX",
        "domain": "NA",
        "topic": "PREP",
        "name": "预备知识",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-GZ-BX-FUNC",
        "seg": "GZ",
        "stage": "BX",
        "domain": "NA",
        "topic": "FUNC",
        "name": "函数",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-GZ-BX-FUNC-CONC",
        "seg": "GZ",
        "stage": "BX",
        "domain": "NA",
        "topic": "FUNC",
        "name": "函数的概念与性质",
        "kind": "unit",
    },
    {
        "code": "GB-MATH-GZ-BX-FUNC-ELF",
        "seg": "GZ",
        "stage": "BX",
        "domain": "NA",
        "topic": "FUNC",
        "name": "幂函数、指数函数、对数函数",
        "kind": "unit",
    },
    {
        "code": "GB-MATH-GZ-BX-FUNC-TRIG",
        "seg": "GZ",
        "stage": "BX",
        "domain": "NA",
        "topic": "FUNC",
        "name": "三角函数",
        "kind": "unit",
    },
    {
        "code": "GB-MATH-GZ-BX-GEOM",
        "seg": "GZ",
        "stage": "BX",
        "domain": "GM",
        "topic": "GEOM",
        "name": "几何与代数（向量·复数·立体几何初步）",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-GZ-BX-GEOM-VEC",
        "seg": "GZ",
        "stage": "BX",
        "domain": "GM",
        "topic": "GEOM",
        "name": "平面向量及其应用",
        "kind": "unit",
    },
    {
        "code": "GB-MATH-GZ-BX-GEOM-CPLX",
        "seg": "GZ",
        "stage": "BX",
        "domain": "GM",
        "topic": "GEOM",
        "name": "复数",
        "kind": "unit",
    },
    {
        "code": "GB-MATH-GZ-BX-GEOM-SOLID",
        "seg": "GZ",
        "stage": "BX",
        "domain": "GM",
        "topic": "GEOM",
        "name": "立体几何初步",
        "kind": "unit",
    },
    {
        "code": "GB-MATH-GZ-BX-STAT",
        "seg": "GZ",
        "stage": "BX",
        "domain": "SP",
        "topic": "STAT",
        "name": "概率与统计",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-GZ-BX-MODEL",
        "seg": "GZ",
        "stage": "BX",
        "domain": "PA",
        "topic": "MODEL",
        "name": "数学建模活动与数学探究活动",
        "kind": "topic",
    },
    # ============ 高中 · 选择性必修 XBX ============
    {
        "code": "GB-MATH-GZ-XBX-FUNC",
        "seg": "GZ",
        "stage": "XBX",
        "domain": "NA",
        "topic": "FUNC",
        "name": "函数（数列·导数）",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-GZ-XBX-FUNC-SEQ",
        "seg": "GZ",
        "stage": "XBX",
        "domain": "NA",
        "topic": "FUNC",
        "name": "数列",
        "kind": "unit",
    },
    {
        "code": "GB-MATH-GZ-XBX-FUNC-DERIV",
        "seg": "GZ",
        "stage": "XBX",
        "domain": "NA",
        "topic": "FUNC",
        "name": "一元函数的导数及其应用",
        "kind": "unit",
    },
    {
        "code": "GB-MATH-GZ-XBX-GEOM",
        "seg": "GZ",
        "stage": "XBX",
        "domain": "GM",
        "topic": "GEOM",
        "name": "几何与代数（空间向量·解析几何）",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-GZ-XBX-GEOM-SVEC",
        "seg": "GZ",
        "stage": "XBX",
        "domain": "GM",
        "topic": "GEOM",
        "name": "空间向量与立体几何",
        "kind": "unit",
    },
    {
        "code": "GB-MATH-GZ-XBX-GEOM-ANALY",
        "seg": "GZ",
        "stage": "XBX",
        "domain": "GM",
        "topic": "GEOM",
        "name": "平面解析几何",
        "kind": "unit",
    },
    {
        "code": "GB-MATH-GZ-XBX-STAT",
        "seg": "GZ",
        "stage": "XBX",
        "domain": "SP",
        "topic": "STAT",
        "name": "概率与统计（计数原理·概率·统计）",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-GZ-XBX-MODEL",
        "seg": "GZ",
        "stage": "XBX",
        "domain": "PA",
        "topic": "MODEL",
        "name": "数学建模活动与数学探究活动",
        "kind": "topic",
    },
    # ============ 高中 · 选修 XX（校本，MVP 阶段 optional）============
    {
        "code": "GB-MATH-GZ-XX-A",
        "seg": "GZ",
        "stage": "XX",
        "domain": "NA",
        "topic": "XXA",
        "name": "选修A类（理工经济，微积分/空间向量/概率统计）",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-GZ-XX-B",
        "seg": "GZ",
        "stage": "XX",
        "domain": "NA",
        "topic": "XXB",
        "name": "选修B类（经济社会理工，微积分/应用统计/模型）",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-GZ-XX-C",
        "seg": "GZ",
        "stage": "XX",
        "domain": "SP",
        "topic": "XXC",
        "name": "选修C类（人文，逻辑/社会调查与数据分析）",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-GZ-XX-D",
        "seg": "GZ",
        "stage": "XX",
        "domain": "PA",
        "topic": "XXD",
        "name": "选修D类（体育艺术，美与数学等）",
        "kind": "topic",
    },
    {
        "code": "GB-MATH-GZ-XX-E",
        "seg": "GZ",
        "stage": "XX",
        "domain": "PA",
        "topic": "XXE",
        "name": "选修E类（拓展/地方/大学先修/生活中的数学）",
        "kind": "topic",
    },
]

# ── 核心素养标签：{code, seg, name} ──
# 义教小学 11 个主要表现；初中把数感/量感/符号意识收敛为"抽象能力"(CO)，其余同名进阶延续同 CODE。
# 素养编码跨小初复用同一 CODE，用 KU 的学段区分"意识"与"能力/观念"，纵向连成素养成长曲线。
LITERACY_TAGS: list[dict] = [
    # 义务教育（SEG=JY）
    {"code": "GB-MATH-CL-JY-NS", "seg": "JY", "name": "数感"},
    {"code": "GB-MATH-CL-JY-QG", "seg": "JY", "name": "量感"},
    {"code": "GB-MATH-CL-JY-SY", "seg": "JY", "name": "符号意识"},
    {
        "code": "GB-MATH-CL-JY-CO",
        "seg": "JY",
        "name": "抽象能力（初中，承数感/量感/符号意识）",
    },
    {"code": "GB-MATH-CL-JY-YS", "seg": "JY", "name": "运算能力"},
    {"code": "GB-MATH-CL-JY-JZ", "seg": "JY", "name": "几何直观"},
    {"code": "GB-MATH-CL-JY-KG", "seg": "JY", "name": "空间观念"},
    {"code": "GB-MATH-CL-JY-TL", "seg": "JY", "name": "推理意识/推理能力"},
    {"code": "GB-MATH-CL-JY-SJ", "seg": "JY", "name": "数据意识/数据观念"},
    {"code": "GB-MATH-CL-JY-MX", "seg": "JY", "name": "模型意识/模型观念"},
    {"code": "GB-MATH-CL-JY-YY", "seg": "JY", "name": "应用意识"},
    {"code": "GB-MATH-CL-JY-CX", "seg": "JY", "name": "创新意识"},
    # 高中（SEG=GZ，各分 L1/L2/L3 三级水平）
    {"code": "GB-MATH-CL-GZ-MA", "seg": "GZ", "name": "数学抽象"},
    {"code": "GB-MATH-CL-GZ-LR", "seg": "GZ", "name": "逻辑推理"},
    {"code": "GB-MATH-CL-GZ-MO", "seg": "GZ", "name": "数学运算"},
    {"code": "GB-MATH-CL-GZ-II", "seg": "GZ", "name": "直观想象"},
    {"code": "GB-MATH-CL-GZ-DA", "seg": "GZ", "name": "数据分析"},
    {"code": "GB-MATH-CL-GZ-MM", "seg": "GZ", "name": "数学建模"},
]

# 高中三级水平 = 掌握度目标阈值分层（不拆 KU）：
#   L1 合格性考试底线 / L2 高考等级性考试 / L3 数学专业进阶
LITERACY_LEVELS = ("L1", "L2", "L3")

# ── 领域 → 默认素养标签建议（主线-素养天然对应，人工微调即可，避免每 KU 从零标注）──
DEFAULT_LITERACY_BY_DOMAIN: dict[str, dict[str, list[str]]] = {
    "NA": {
        "JY": ["GB-MATH-CL-JY-CO", "GB-MATH-CL-JY-YS"],
        "GZ": ["GB-MATH-CL-GZ-MA", "GB-MATH-CL-GZ-MO"],
    },
    "GM": {
        "JY": ["GB-MATH-CL-JY-JZ", "GB-MATH-CL-JY-KG"],
        "GZ": ["GB-MATH-CL-GZ-II", "GB-MATH-CL-GZ-LR"],
    },
    "SP": {"JY": ["GB-MATH-CL-JY-SJ"], "GZ": ["GB-MATH-CL-GZ-DA"]},
    "PA": {
        "JY": ["GB-MATH-CL-JY-MX", "GB-MATH-CL-JY-YY"],
        "GZ": ["GB-MATH-CL-GZ-MM", "GB-MATH-CL-GZ-LR"],
    },
}

_BY_CODE = {n["code"]: n for n in STD_NODES}
_LIT_BY_CODE = {t["code"]: t for t in LITERACY_TAGS}


def get_node(code: str) -> Optional[dict]:
    """按主编码取课标节点；未知返回 None。"""
    return _BY_CODE.get(code)


def is_valid_std_code(code: str) -> bool:
    """是否为已登记的课标内容主编码。"""
    return code in _BY_CODE


def is_valid_literacy(code: str) -> bool:
    """是否为已登记的核心素养标签（可带 -L1/-L2/-L3 后缀）。"""
    base = code
    for lv in LITERACY_LEVELS:
        if code.endswith(f"-{lv}"):
            base = code[: -(len(lv) + 1)]
            break
    return base in _LIT_BY_CODE


def suggest_literacy(domain: str, seg: str) -> list[str]:
    """按领域+学段给默认素养标签建议（KU 对齐初始化用）。未知返回空。"""
    return DEFAULT_LITERACY_BY_DOMAIN.get(domain, {}).get(seg, [])


__all__ = [
    "STD_NODES",
    "LITERACY_TAGS",
    "LITERACY_LEVELS",
    "DEFAULT_LITERACY_BY_DOMAIN",
    "get_node",
    "is_valid_std_code",
    "is_valid_literacy",
    "suggest_literacy",
]
