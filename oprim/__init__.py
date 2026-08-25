"""Mneme 3O: oprim — 单次原子操作（Echo-Loop 学习闭环原语）"""

# Echo-Loop 学习闭环原语
from .echo_loop import (
    # 盲听阶段
    blind_listen_generate,
    BlindListenInput,
    BlindListenOutput,
    # 精听阶段
    intensive_listen_parse,
    IntensiveListenInput,
    IntensiveListenOutput,
    # 跟读阶段
    shadowing_evaluate,
    ShadowingInput,
    ShadowingOutput,
    # 复述阶段
    retell_evaluate,
    RetellInput,
    RetellOutput,
)

# 复用 vendor 中已验证的核心算法
from vendor.oprim.bkt import bkt_update, classify_error
from vendor.oprim.fsrs_engine import fsrs_review, fsrs_retrievability, fsrs_map_rating
from vendor.oprim.cognitive import cognitive_update

__all__ = [
    # Echo-Loop 原语
    "blind_listen_generate",
    "BlindListenInput",
    "BlindListenOutput",
    "intensive_listen_parse",
    "IntensiveListenInput",
    "IntensiveListenOutput",
    "shadowing_evaluate",
    "ShadowingInput",
    "ShadowingOutput",
    "retell_evaluate",
    "RetellInput",
    "RetellOutput",
    # 复用核心算法
    "bkt_update",
    "classify_error",
    "fsrs_review",
    "fsrs_retrievability",
    "fsrs_map_rating",
    "cognitive_update",
]
