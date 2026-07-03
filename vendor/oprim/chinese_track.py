"""L4 · 语文双轨分类。纯函数，确定性。

据评审：语文不是 KU 掌握型领域，须**双轨**——
- **记诵轨**（recite）：文言实词虚词、成语、字形字音、文化常识、名句名篇 → FSRS 间隔重复（记忆单元）。
- **素养轨**（literacy）：阅读理解各类、写作、诗词鉴赏 → 阅读策略教学（交互式教学法：预测/提问/
  澄清/总结）+ 作文提纲脚手架–rubric–修订环，**不套 BKT+题库掌握模型**（否则空心闭环）。

按 ku_type 硬分类，供前端/调度路由：记诵→FSRS 背诵练习；素养→阅读引导/作文引导。
"""

from __future__ import annotations

# 记诵轨 ku_type（可 FSRS 化的记忆型）
_RECITE_TYPES = {
    "wenyan_word",  # 文言实词
    "wenyan_syntax",  # 文言虚词/句式
    "chengyu",  # 成语
    "zixing_ziyin",  # 字形字音
    "wenhua_changshi",  # 文化常识
    "mingju",  # 名句
    "mingpian",  # 名篇（背诵默写）
}

# 素养轨 ku_type（阅读策略 / 写作 rubric，不 FSRS）
_LITERACY_TYPES = {
    "xiezuo",  # 写作
    "shici_jianshang",  # 诗词鉴赏
    "jixuwen_yuedu",  # 记叙文阅读
    "xiaoshuo_yuedu",  # 小说阅读
    "mingzhu_yuedu",  # 名著阅读
    "wenyan_yuedu",  # 文言文阅读
    "xinxi_yuedu",  # 信息类阅读
    "shuomingwen_yuedu",  # 说明文阅读
    "yishu_yuedu",  # 议论文阅读
}


def chinese_track(ku_type: str | None) -> str:
    """语文 KU 属哪一轨：``recite``（记诵/FSRS）| ``literacy``（素养/策略）。

    未知 ku_type：含 'yuedu'(阅读)/'xiezuo'(写作)/'jianshang'(鉴赏) → literacy，否则默认 recite。
    """
    t = (ku_type or "").strip()
    if t in _RECITE_TYPES:
        return "recite"
    if t in _LITERACY_TYPES:
        return "literacy"
    if any(k in t for k in ("yuedu", "xiezuo", "jianshang", "zuowen")):
        return "literacy"
    return "recite"


def is_fsrs_eligible(ku_type: str | None) -> bool:
    """记诵轨才进 FSRS（记忆单元）；素养轨不套记忆调度。"""
    return chinese_track(ku_type) == "recite"


__all__ = ["chinese_track", "is_fsrs_eligible"]
