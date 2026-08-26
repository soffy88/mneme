"""Mneme 3O: oprim — 单次原子操作（Echo-Loop 学习闭环原语）"""

# The repository keeps a small compatibility package next to the vendored 3O
# runtime.  Extend this package path before importing vendored modules so their
# absolute ``oprim._...`` imports resolve in a fresh checkout as well as in the
# pre-existing developer environment.
from pathlib import Path

__path__.append(str(Path(__file__).resolve().parent.parent / "vendor" / "oprim"))

# Echo-Loop 学习闭环原语
from .echo_loop import (  # noqa: E402
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
from vendor.oprim.bkt import bkt_update, classify_error  # noqa: E402
from vendor.oprim.fsrs_engine import (  # noqa: E402
    fsrs_review,
    fsrs_retrievability,
    fsrs_map_rating,
)

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
]
