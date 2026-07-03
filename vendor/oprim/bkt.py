"""
BKT 知识追踪引擎 — 公开别名层（无前缀命名）
==========================================
**单一事实来源 = `oprim._cognitive`**（被 AUC 仿真验证，且拥有 KCState/FSRS）。
本模块不再复制算法，只把同一实现以「无前缀」名字暴露给历史调用方
（`oskill.cognitive_state` 等），杜绝「改一份漏另一份」(D5 漂移)。

合并依据（2026-06-28）：在 19440 个真实参数组合下，旧 `bkt.py` 与 `_cognitive`
的 `p_mastery / long_term / predict / classify` 输出**逐位一致**（max|Δ|=0），
故本次收敛为**零行为变化**。差异只存在于不可达的数值极端（R 恰为 0 的 clip、
浮点平局），实际参数空间不出现。

名称映射（无前缀 → canonical）：
    bkt_update          = bkt_update
    classify_error      = bkt_classify_error
    predict_correct     = bkt_predict_correct
    new_state_from_prior= bkt_new_state
    exp_forgetting      = exp_forgetting
"""

from __future__ import annotations

from oprim._cognitive import (  # noqa: F401  (re-export 别名层)
    bkt_update as bkt_update,
    bkt_classify_error as classify_error,
    bkt_error_weights as error_weights,
    bkt_predict_correct as predict_correct,
    bkt_new_state as new_state_from_prior,
    exp_forgetting as exp_forgetting,
    _item_adjust as _item_adjust,
    _GAMMA_SLIP as _GAMMA_SLIP,
    _GAMMA_GUESS as _GAMMA_GUESS,
)
from oprim.types import KCState as KCState  # 历史可达性（部分调用方从此处取 KCState）

__version__ = "0.2.0"
__manifest__ = {
    "version": __version__,
    "updated_at": "2026-06-28",
    "single_source": "oprim._cognitive",
    "elements": [
        {
            "name": "bkt_update",
            "layer": "oprim",
            "summary": "forgetting-aware BKT 更新（难度感知，别名→_cognitive）",
        },
        {
            "name": "classify_error",
            "layer": "oprim",
            "summary": "答错时判定错误根因（别名→bkt_classify_error）",
        },
        {
            "name": "error_weights",
            "layer": "oprim",
            "summary": "答错根因两假设权重（别名→bkt_error_weights，红线公式单源）",
        },
        {
            "name": "predict_correct",
            "layer": "oprim",
            "summary": "预测下一题答对概率（别名→bkt_predict_correct）",
        },
        {
            "name": "exp_forgetting",
            "layer": "oprim",
            "summary": "指数遗忘近似（别名→_cognitive）",
        },
        {
            "name": "new_state_from_prior",
            "layer": "oprim",
            "summary": "从 BKT 先验字典创建 KCState（别名→bkt_new_state）",
        },
    ],
}
