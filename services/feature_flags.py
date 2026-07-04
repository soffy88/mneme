"""U.24 教学机制 feature-flag 化：pedagogy/01-08 各机制的开关读取。

同 fsrs_optimize_service.fitting_enabled()/TEACHING_ENGINE_ENABLED 既有约定——
env 一票否决，默认开（保留当前上线行为），显式设为 "0"/"false" 才关闭。这是运维
急停开关，不是 A/B 实验分流（那个是 experiment_service 的 EXPERIMENT_* 系列）。
"""

from __future__ import annotations

import os


def pedagogy_enabled(env_name: str) -> bool:
    """env 未设置或非 "0"/"false" 均视为开（默认保留现状）。"""
    return os.environ.get(env_name, "1").lower() not in ("0", "false")


# pedagogy/01-08 对应的 env 变量名（单源，散落字面量一律迁移引用此处）
PEDAGOGY_FRINGE = "PEDAGOGY_FRINGE_ENABLED"  # 01 掌握门控+知识空间选题
PEDAGOGY_LEAGUE = "PEDAGOGY_LEAGUE_ENABLED"  # 02 SDT 留存-归属(匿名联赛)
PEDAGOGY_OLM = "PEDAGOGY_OLM_ENABLED"  # 03 开放学习者模型
PEDAGOGY_SELF_EXPLANATION = "PEDAGOGY_SELF_EXPLANATION_ENABLED"  # 04 自我解释采集
PEDAGOGY_GROWTH_FEEDBACK = "PEDAGOGY_GROWTH_FEEDBACK_ENABLED"  # 05 成长型思维反馈
PEDAGOGY_EXAM_AWARE = "PEDAGOGY_EXAM_AWARE_ENABLED"  # 06 考期感知调度
PEDAGOGY_FINE_FEEDBACK = "PEDAGOGY_FINE_FEEDBACK_ENABLED"  # 07 刻意练习细颗粒反馈
PEDAGOGY_AFFECT = "PEDAGOGY_AFFECT_ENABLED"  # 08 情感感知
