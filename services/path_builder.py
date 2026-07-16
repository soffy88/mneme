"""path_builder — 学习 path 构建期校验（Layer4，架构 A）。

D1.3 防活锁：把"定性 KC 必须有 rubric 才能 assess"的校验**前移到建 path 时**，
绝不进回合循环——否则 `next_objective` 可能对无 rubric 的定性 KC 反复派 assess，
工具因无 rubric 拒绝，形成活锁。

意图来源与运行时门控**分离**（见 `qualitative_intent`）：build_path 校验的是
"**意图**为定性但 gate.rubric 缺记录"的 KC；这样即便 rubric 被删（运行时 resolve
会降级为 quantitative）也能被 authoring 校验捕获。对应验收 V12。

`NextStep.blocked` 语义（把"缺 rubric"作为可返回状态而非异常）留 W2。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from services import gate_store
from services.qualitative_intent import QUALITATIVE_INTENT


class PathBuildError(ValueError):
    """建 path 时发现意图定性但缺 rubric 的 KC。`missing` 为**完整**缺失清单。"""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(
            "路径构建失败：以下意图定性的 KC 在 gate.rubric 缺记录（不可 assess）："
            + ", ".join(missing)
        )


async def build_path(
    db: AsyncSession,
    kc_ids: list[str],
    *,
    intent: Optional[Iterable[str]] = None,
) -> list[str]:
    """校验并返回学习 path。

    对 path 中**意图定性**的每个 KC 断言 gate.rubric 有记录；任一缺失则收集**全部**
    缺失项后一次性 raise（不是遇到首个就抛，便于 authoring 一次补齐）。

    Args:
        db: async session。
        kc_ids: 待构建的学习 path。
        intent: 定性意图集合（默认取 `qualitative_intent.QUALITATIVE_INTENT`；
            测试可注入以覆盖多缺失场景）。

    Returns:
        原样的 kc_ids（校验通过）。

    Raises:
        PathBuildError: 存在意图定性但无 rubric 的 KC，`.missing` 为完整清单。
    """
    intent_set = frozenset(intent) if intent is not None else QUALITATIVE_INTENT

    missing: list[str] = []
    for kc in kc_ids:
        if kc in intent_set and not await gate_store.has_rubric(db, kc):
            missing.append(kc)

    if missing:
        raise PathBuildError(missing)
    return list(kc_ids)
