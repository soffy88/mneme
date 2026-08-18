"""
广东高中数学知识点字典 (v2) — 旧版兼容 re-export，内容见 guangdong_math_kc_v2.py。

从 v2 版本导入所有内容，保持向后兼容。
v2 改进：62 个 KC（原 29 个），粒度更细，匹配 KU 包 cluster 细度。
"""

from data.guangdong_math_kc_v2 import (  # noqa: F401, F403
    KC_LIST, KC_INDEX, get_kc, get_bkt_prior,
    all_prerequisites, total_gaokao_score, kc_summary,
    MIDDLE_SCHOOL_KC_STUBS,
)