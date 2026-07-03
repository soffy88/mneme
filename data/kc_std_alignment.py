"""
广东高中数学 KC → 国家课标对齐表 (KC ↔ Curriculum Standard)
=========================================================
把 data.guangdong_math_kc.KC_LIST 的每个 KC 挂到 data.curriculum_std 的课标主编码上，
形成纵向可串联的档案数据（护城河）。

对齐记录字段：
- std       : 课标内容主编码（唯一、挂到能定位的最细层级），必填。
- level     : 高中三级水平目标（L1 合格底线 / L2 高考等级 / L3 专业进阶/压轴），做掌握度目标阈值，不拆 KC。
- literacy  : 素养标签覆盖（可选）；缺省时按主编码所在领域用 suggest_literacy 派生默认值（单源）。

挂靠原则（见 curriculum_std 文档）：一 KC 一主编码；素养 1–3 个有主次；水平不拆 KC。
本表覆盖 KC_LIST 全部条目（测试守卫全覆盖 + 编码合法）。素养默认值由领域推导，
教研逐条精修时在 literacy 字段显式覆盖即可。
"""

from __future__ import annotations

from typing import Optional

from data.curriculum_std import (
    get_node,
    suggest_literacy,
)

# kc_id -> {std, level, literacy?}
KC_STD_ALIGN: dict[str, dict] = {
    # ==== 必修（BX）· 高一 ====
    "GDMATH-SET-01": {"std": "GB-MATH-GZ-BX-PREP", "level": "L1"},
    "GDMATH-SET-02": {
        "std": "GB-MATH-GZ-BX-PREP",
        "level": "L1",
        "literacy": ["GB-MATH-CL-GZ-LR", "GB-MATH-CL-GZ-MA"],
    },
    "GDMATH-INEQ-01": {"std": "GB-MATH-GZ-BX-PREP", "level": "L2"},
    "GDMATH-FUNC-01": {"std": "GB-MATH-GZ-BX-FUNC-CONC", "level": "L2"},
    "GDMATH-FUNC-02": {"std": "GB-MATH-GZ-BX-FUNC-CONC", "level": "L2"},
    "GDMATH-FUNC-03": {"std": "GB-MATH-GZ-BX-FUNC-ELF", "level": "L2"},
    "GDMATH-TRIG-01": {"std": "GB-MATH-GZ-BX-FUNC-TRIG", "level": "L2"},
    "GDMATH-TRIG-02": {"std": "GB-MATH-GZ-BX-FUNC-TRIG", "level": "L2"},
    "GDMATH-VEC-01": {"std": "GB-MATH-GZ-BX-GEOM-VEC", "level": "L2"},
    "GDMATH-TRIG-03": {"std": "GB-MATH-GZ-BX-GEOM-VEC", "level": "L2"},
    "GDMATH-COMPLEX-01": {"std": "GB-MATH-GZ-BX-GEOM", "level": "L1"},
    "GDMATH-SOLID-01": {"std": "GB-MATH-GZ-BX-GEOM-SOLID", "level": "L2"},
    "GDMATH-STAT-01": {"std": "GB-MATH-GZ-BX-STAT", "level": "L2"},
    "GDMATH-PROB-01": {"std": "GB-MATH-GZ-BX-STAT", "level": "L2"},
    # ==== 选择性必修（XBX）· 高二/高三 ====
    "GDMATH-SVEC-01": {"std": "GB-MATH-GZ-XBX-GEOM-SVEC", "level": "L2"},
    "GDMATH-LINE-01": {"std": "GB-MATH-GZ-XBX-GEOM-ANALY", "level": "L2"},
    "GDMATH-CIRCLE-01": {"std": "GB-MATH-GZ-XBX-GEOM-ANALY", "level": "L2"},
    "GDMATH-CONIC-01": {"std": "GB-MATH-GZ-XBX-GEOM-ANALY", "level": "L2"},
    "GDMATH-CONIC-02": {"std": "GB-MATH-GZ-XBX-GEOM-ANALY", "level": "L2"},
    "GDMATH-CONIC-03": {"std": "GB-MATH-GZ-XBX-GEOM-ANALY", "level": "L2"},
    "GDMATH-CONIC-04": {"std": "GB-MATH-GZ-XBX-GEOM-ANALY", "level": "L3"},
    "GDMATH-SEQ-01": {"std": "GB-MATH-GZ-XBX-FUNC-SEQ", "level": "L2"},
    "GDMATH-SEQ-02": {"std": "GB-MATH-GZ-XBX-FUNC-SEQ", "level": "L3"},
    "GDMATH-DERIV-01": {"std": "GB-MATH-GZ-XBX-FUNC-DERIV", "level": "L2"},
    "GDMATH-DERIV-02": {"std": "GB-MATH-GZ-XBX-FUNC-DERIV", "level": "L3"},
    "GDMATH-DERIV-03": {"std": "GB-MATH-GZ-XBX-FUNC-DERIV", "level": "L3"},
    "GDMATH-COUNT-01": {"std": "GB-MATH-GZ-XBX-STAT", "level": "L2"},
    "GDMATH-PROB-02": {
        "std": "GB-MATH-GZ-XBX-STAT",
        "level": "L2",
        "literacy": ["GB-MATH-CL-GZ-DA", "GB-MATH-CL-GZ-MO"],
    },
    "GDMATH-STAT-02": {
        "std": "GB-MATH-GZ-XBX-STAT",
        "level": "L2",
        "literacy": ["GB-MATH-CL-GZ-DA", "GB-MATH-CL-GZ-MM"],
    },
}


def get_alignment(kc_id: str) -> Optional[dict]:
    """取某 KC 的课标对齐记录：{primary_std_code, literacy_tags, target_level}。

    literacy_tags：显式覆盖优先，否则按主编码所在领域 suggest_literacy 派生（单源默认）。
    未登记的 kc_id 返回 None。
    """
    rec = KC_STD_ALIGN.get(kc_id)
    if rec is None:
        return None
    node = get_node(rec["std"])
    if rec.get("literacy"):
        literacy = list(rec["literacy"])
    elif node is not None:
        literacy = suggest_literacy(node["domain"], node["seg"])
    else:
        literacy = []
    return {
        "primary_std_code": rec["std"],
        "literacy_tags": literacy,
        "target_level": rec["level"],
    }


__all__ = ["KC_STD_ALIGN", "get_alignment"]
