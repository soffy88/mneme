"""qualitative_intent — authoring-time 声明哪些 KC **意图**为定性门控。

与运行时 `gate_store.resolve_gate_type`（D2.2 净规则：rubric 存在性）**刻意分离**：
- 运行时门控只认 rubric（有 rubric ⟺ qualitative），保证不存在"定性但无 rubric"的活状态。
- 但"某 KC 应当是定性的"这一**意图**必须能在 rubric 尚未就位 / 会话中途被删时仍然成立，
  否则删 rubric 会静默把它降级为 quantitative 而无人察觉。本模块即该意图源。

`build_path` 用它做 authoring-time 校验：**意图为定性但 gate.rubric 缺记录 → 构建失败**
（SPEC §3.6 / D1.3 防活锁；对应验收 V12）。这是 authoring-only 信号，**不参与运行时判分/门控路由**。

白名单驱动的批量意图（xiezuo、*_yuedu、shici_jianshang…）随非数学科目于 W2 恢复（决策 A1）；
W1 数学域只有 ku004 一条手工意图。
"""

from __future__ import annotations

# W1 手工登记的定性意图 KC（数学域仅此一条：DoD 定性桩）。
QUALITATIVE_INTENT: frozenset[str] = frozenset(
    {
        "renjiao-math-g10-a-ku004",  # 函数的概念与表示
    }
)


def is_qualitative_intent(kc_id: str) -> bool:
    """该 KC 是否被登记为**意图**定性门控（authoring 信号，非运行时门控）。"""
    return kc_id in QUALITATIVE_INTENT
