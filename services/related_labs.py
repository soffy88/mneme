"""相关实验：把知识点映射到 WeduLab（wedulab.com）的公开在线实验。

WeduLab 是 edulab 作者（wy51ai）的在线实验站，源码未开源、无许可证，所以这里
**只做外链**：不复制、不嵌入其代码或页面资源，Studio 以新窗口打开，并注明来源。

匹配规则（确定性、无 LLM）：
1. ``kc_id`` 前缀直配（如 ``GDMATH-CONIC-*`` → 圆锥曲线）；
2. 文本关键词命中（知识点名 / 错因标签 / 题干摘要），按命中关键词的总长度打分；
3. 可选 ``subject`` 过滤（math / physics / chemistry / biology / geography / history）。
没有可靠命中时返回空列表，不硬凑。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

SOURCE_NAME = "WeduLab"
SOURCE_HOME = "https://wedulab.com/"
_BASE = "https://wedulab.com/labs/"

SUBJECT_LABELS = {
    "math": "数学",
    "physics": "物理",
    "chemistry": "化学",
    "biology": "生物",
    "geography": "地理",
    "history": "历史",
}


@dataclass(frozen=True)
class Lab:
    slug: str
    title: str
    subject: str
    stages: tuple[str, ...]
    topics: tuple[str, ...]
    keywords: tuple[str, ...]

    @property
    def url(self) -> str:
        return f"{_BASE}{self.slug}"

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["url"] = self.url
        d["subject_label"] = SUBJECT_LABELS[self.subject]
        d["stages"] = list(self.stages)
        d["topics"] = list(self.topics)
        d.pop("keywords")
        return d


LABS: tuple[Lab, ...] = (
    # ---- 物理 ----
    Lab(
        "volt",
        "VoltLab 电学实验台",
        "physics",
        ("初中", "高中"),
        ("串并联电路", "欧姆定律", "电表使用", "电功率"),
        (
            "电路",
            "串联",
            "并联",
            "欧姆定律",
            "电流",
            "电压",
            "电阻",
            "电功率",
            "电流表",
            "电压表",
            "伏安",
            "小灯泡",
            "滑动变阻器",
            "焦耳",
        ),
    ),
    Lab(
        "motion",
        "运动与力 · MotionLab",
        "physics",
        ("初中", "高中"),
        ("匀变速直线运动", "牛顿第二定律", "摩擦力", "动量守恒"),
        (
            "匀变速",
            "匀速直线",
            "自由落体",
            "加速度",
            "牛顿第二定律",
            "牛顿运动定律",
            "摩擦力",
            "斜面",
            "超重",
            "失重",
            "机械能守恒",
            "动量守恒",
            "动量",
            "打点计时器",
            "纸带",
            "光电门",
            "气垫导轨",
            "受力分析",
            "弹簧测力计",
        ),
    ),
    Lab(
        "optics",
        "光学实验台 · OpticsLab",
        "physics",
        ("初中", "高中"),
        ("折射定律", "凸透镜成像", "双缝干涉", "光的偏振"),
        (
            "光的反射",
            "光的折射",
            "折射",
            "反射定律",
            "全反射",
            "光纤",
            "色散",
            "三棱镜",
            "凸透镜",
            "透镜成像",
            "近视",
            "远视",
            "双缝干涉",
            "干涉",
            "衍射",
            "光栅",
            "薄膜干涉",
            "偏振",
        ),
    ),
    Lab(
        "waves",
        "振动与波 · WaveLab",
        "physics",
        ("初中", "高中"),
        ("简谐运动", "共振", "驻波", "多普勒效应"),
        (
            "简谐运动",
            "弹簧振子",
            "单摆",
            "受迫振动",
            "共振",
            "机械波",
            "横波",
            "纵波",
            "驻波",
            "波的干涉",
            "多普勒",
            "声波",
            "共鸣",
            "示波器",
            "振动",
        ),
    ),
    Lab(
        "fields",
        "电场与磁场 · FieldLab",
        "physics",
        ("高中",),
        ("电场线", "洛伦兹力", "电磁感应", "交流电"),
        (
            "电场",
            "电场线",
            "等势面",
            "电势",
            "电容器",
            "示波管",
            "磁场",
            "磁感线",
            "安培力",
            "洛伦兹力",
            "质谱仪",
            "回旋加速器",
            "电磁感应",
            "楞次定律",
            "感应电流",
            "交流电",
            "发电机",
            "带电粒子",
        ),
    ),
    # ---- 地理 ----
    Lab(
        "contour",
        "等高线 3D 课堂",
        "geography",
        ("初中", "高中"),
        ("等高线形成", "山顶·山脊·山谷", "鞍部·陡崖·盆地", "地形剖面图"),
        ("等高线", "山脊", "山谷", "鞍部", "陡崖", "地形剖面", "地形图", "海拔"),
    ),
    Lab(
        "atmos",
        "大气环流粒子课堂",
        "geography",
        ("高中",),
        ("热力环流", "海陆风·山谷风", "三圈环流", "气压带风带"),
        (
            "热力环流",
            "大气环流",
            "三圈环流",
            "气压带",
            "风带",
            "海陆风",
            "山谷风",
            "城市热岛",
            "季风",
        ),
    ),
    Lab(
        "earth",
        "地球运动课堂",
        "geography",
        ("初中", "高中"),
        ("昼夜交替", "直射点移动", "昼夜长短", "正午太阳高度"),
        (
            "地球自转",
            "地球公转",
            "晨昏线",
            "黄赤交角",
            "直射点",
            "昼夜长短",
            "正午太阳高度",
            "四季",
            "昼夜交替",
            "地球运动",
        ),
    ),
    Lab(
        "drift",
        "海陆的变迁",
        "geography",
        ("初中",),
        ("沧海桑田", "大陆漂移", "板块构造", "火山地震带"),
        (
            "大陆漂移",
            "板块",
            "板块构造",
            "海陆变迁",
            "沧海桑田",
            "火山",
            "地震带",
            "泛大陆",
            "魏格纳",
        ),
    ),
    Lab(
        "water",
        "水循环三维沙盘 · WaterCycle",
        "geography",
        ("初中", "高中"),
        ("水循环环节", "三类水循环", "海绵城市", "水量平衡"),
        (
            "水循环",
            "蒸发",
            "降水",
            "径流",
            "下渗",
            "地下径流",
            "海绵城市",
            "水量平衡",
            "水汽输送",
        ),
    ),
    # ---- 生物 ----
    Lab(
        "cell",
        "细胞 · 三维结构",
        "biology",
        ("高中",),
        ("细胞器", "生物膜系统", "物质跨膜运输", "分泌蛋白"),
        (
            "细胞结构",
            "细胞器",
            "线粒体",
            "叶绿体",
            "内质网",
            "高尔基体",
            "核糖体",
            "细胞膜",
            "生物膜",
            "流动镶嵌",
            "跨膜运输",
            "主动运输",
            "协助扩散",
            "分泌蛋白",
            "原核细胞",
            "真核细胞",
        ),
    ),
    Lab(
        "micro",
        "显微镜实验台 · MicroLab",
        "biology",
        ("初中", "高中"),
        ("显微镜使用", "观察细胞", "质壁分离", "有丝分裂"),
        (
            "显微镜",
            "准焦螺旋",
            "装片",
            "玻片",
            "观察细胞",
            "质壁分离",
            "有丝分裂",
            "油镜",
            "血球计数板",
            "测微尺",
        ),
    ),
    Lab(
        "pea",
        "孟德尔豌豆杂交实验 · PeaLab",
        "biology",
        ("初中", "高中"),
        ("人工异花授粉", "分离定律", "自由组合定律", "假说—演绎法"),
        (
            "孟德尔",
            "豌豆",
            "杂交",
            "分离定律",
            "自由组合",
            "测交",
            "性状分离",
            "遗传规律",
            "基因型",
            "表现型",
            "假说演绎",
            "卡方",
        ),
    ),
    # ---- 化学 ----
    Lab(
        "periodic",
        "元素周期表 · PeriodicLab",
        "chemistry",
        ("初中", "高中"),
        ("周期律", "电子层", "物态与温度", "元素发现史"),
        (
            "元素周期表",
            "周期律",
            "元素周期律",
            "原子半径",
            "电负性",
            "电离能",
            "主族",
            "同周期",
            "同主族",
            "金属性",
            "非金属性",
        ),
    ),
    Lab(
        "mechanism",
        "反应机理 · 分子动画",
        "chemistry",
        ("高中", "大学"),
        ("酯化反应", "同位素示踪", "电子转移", "反应机理"),
        (
            "反应机理",
            "酯化",
            "同位素示踪",
            "电子转移",
            "有机反应",
            "取代反应",
            "加成反应",
            "消去反应",
            "离子反应",
            "氧化还原",
            "离子方程式",
            "化学方程式",
            "配平",
        ),
    ),
    Lab(
        "vsepr",
        "分子构型 · VSEPR",
        "chemistry",
        ("高中", "大学"),
        ("价层电子对互斥", "杂化轨道", "分子极性", "手性分子"),
        (
            "分子构型",
            "价层电子对",
            "VSEPR",
            "杂化",
            "杂化轨道",
            "键角",
            "孤电子对",
            "分子极性",
            "极性分子",
            "手性",
            "空间构型",
        ),
    ),
    Lab(
        "orbital",
        "原子轨道 · 电子云",
        "chemistry",
        ("高中", "大学"),
        ("电子云", "轨道形状", "构造原理", "量子数"),
        (
            "原子轨道",
            "电子云",
            "电子排布",
            "构造原理",
            "量子数",
            "能级",
            "s轨道",
            "p轨道",
            "d轨道",
            "泡利",
            "洪特",
        ),
    ),
    Lab(
        "reaction",
        "化学反应 · 微观世界",
        "chemistry",
        ("高中",),
        ("有效碰撞", "反应速率", "化学平衡", "链式反应"),
        (
            "有效碰撞",
            "活化能",
            "活化分子",
            "反应速率",
            "化学反应速率",
            "催化剂",
            "化学平衡",
            "平衡移动",
            "勒夏特列",
            "浓度对",
            "压强对",
            "链式反应",
        ),
    ),
    # ---- 数学 ----
    Lab(
        "geo",
        "立体几何 · GeoSpace",
        "math",
        ("高中",),
        ("展开图", "截面", "空间角", "空间向量"),
        (
            "立体几何",
            "空间几何体",
            "展开图",
            "三视图",
            "斜二测",
            "截面",
            "二面角",
            "线面角",
            "异面直线",
            "空间角",
            "空间向量",
            "外接球",
            "内切球",
            "正四面体",
            "正方体",
            "棱锥",
            "棱柱",
            "线面平行",
            "面面垂直",
            "线面垂直",
            "表面积",
            "体积",
        ),
    ),
    Lab(
        "conic",
        "圆锥曲线 · ConicLab",
        "math",
        ("高中",),
        ("圆锥截线", "焦点与离心率", "光学性质", "判别式"),
        (
            "圆锥曲线",
            "椭圆",
            "双曲线",
            "抛物线",
            "离心率",
            "焦点",
            "准线",
            "弦长",
            "中点弦",
            "判别式",
            "定点定值",
        ),
    ),
    Lab(
        "func",
        "函数图像 · FuncLab",
        "math",
        ("高中",),
        ("图像变换", "三角函数", "导数", "二分法"),
        (
            "函数图像",
            "图象变换",
            "图像变换",
            "平移",
            "伸缩",
            "指数函数",
            "对数函数",
            "反函数",
            "三角函数",
            "正弦曲线",
            "五点法",
            "导数",
            "切线",
            "单调性",
            "极值",
            "零点",
            "二分法",
            "定积分",
            "黎曼和",
            "函数",
        ),
    ),
    Lab(
        "construct",
        "尺规作图 · ConstructLab",
        "math",
        ("初中",),
        ("尺规作图", "全等判定", "相似", "闯关"),
        (
            "尺规作图",
            "作图",
            "全等",
            "全等三角形",
            "相似三角形",
            "位似",
            "相似比",
            "垂直平分线",
            "角平分线",
        ),
    ),
    Lab(
        "pythagoras",
        "勾股定理 · PythagoLab",
        "math",
        ("初中",),
        ("拼图证明", "出入相补", "欧几里得", "勾股数"),
        ("勾股定理", "勾股数", "直角三角形", "赵爽弦图", "出入相补"),
    ),
    Lab(
        "wonder",
        "趣味数学 · WonderLab",
        "math",
        ("初中", "高中"),
        ("分形", "莫比乌斯带", "黄金分割", "叶序"),
        (
            "分形",
            "谢尔宾斯基",
            "科赫雪花",
            "莫比乌斯",
            "黄金分割",
            "斐波那契",
            "黄金角",
        ),
    ),
    # ---- 历史 ----
    Lab(
        "war",
        "著名战役沙盘 · WarTable",
        "history",
        ("初中", "高中"),
        ("分阶段推演", "以少胜多", "地形与战法", "胜负原因"),
        (
            "长平之战",
            "巨鹿之战",
            "官渡之战",
            "赤壁之战",
            "淝水之战",
            "温泉关",
            "高加米拉",
            "坎尼",
            "黑斯廷斯",
            "以少胜多",
            "战役",
        ),
    ),
)

BY_SLUG: dict[str, Lab] = {lab.slug: lab for lab in LABS}

# kc_id 前缀 → 实验（确定性直配，优先于关键词）
KC_PREFIX_MAP: dict[str, tuple[str, ...]] = {
    "GDMATH-CONIC": ("conic",),
    "GDMATH-SOLID": ("geo",),
    "GDMATH-SVEC": ("geo",),
    "GDMATH-FUNC": ("func",),
    "GDMATH-DERIV": ("func",),
    "GDMATH-TRIG": ("func",),
}


def catalog() -> list[dict[str, object]]:
    return [lab.to_dict() for lab in LABS]


def match_related_labs(
    text: str = "",
    *,
    kc_id: str | None = None,
    subject: str | None = None,
    limit: int = 3,
) -> list[dict[str, object]]:
    """按 kc_id 前缀与关键词为一个知识点找相关实验；无可靠命中返回 []。"""
    limit = max(1, min(int(limit), 10))
    scores: dict[str, float] = {}
    if kc_id:
        key = kc_id.strip().upper()
        for prefix, slugs in KC_PREFIX_MAP.items():
            if key.startswith(prefix):
                for slug in slugs:
                    scores[slug] = scores.get(slug, 0.0) + 100.0
    haystack = (text or "").strip()
    if haystack:
        low = haystack.lower()
        for lab in LABS:
            hit = sum(len(k) for k in lab.keywords if k.lower() in low)
            if hit:
                scores[lab.slug] = scores.get(lab.slug, 0.0) + hit
    ranked = [
        BY_SLUG[s] for s, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    if subject:
        ranked = [lab for lab in ranked if lab.subject == subject]
    out = []
    for lab in ranked[:limit]:
        d = lab.to_dict()
        d["score"] = scores[lab.slug]
        out.append(d)
    return out
