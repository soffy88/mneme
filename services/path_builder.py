"""path_builder — 学习 path 构建期校验（Layer4，架构 A）。

D1.3 防活锁：把"定性 KC 必须有 rubric 才能 assess"的校验**前移到建 path 时**，
绝不进回合循环——否则 `next_objective` 可能对无 rubric 的定性 KC 反复派 assess，
工具因无 rubric 拒绝，形成活锁。

意图来源（gate.qualitative_intent）与判据（gate.rubric）**分表**（R2 §5 / M1）：build_path
校验的是"**意图**为定性（intent 表命中）但 gate.rubric 缺记录"的 KC。M1 后 resolve_gate_type
也读意图表，故 resolve 与 build_path 对同一 KC 的定性判定一致；删 rubric 只撤销判据、不撤销
意图，V12「删 ku004 rubric → build_path 失败」由此有牙齿。对应验收 V12。

`NextStep.blocked` 语义（把"缺 rubric"作为可返回状态而非异常）留 W2。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from services import gate_store


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
        intent: 定性意图集合覆盖（默认 None → 逐 KC 查 gate.qualitative_intent；
            测试可注入显式集合以覆盖多缺失场景）。

    Returns:
        原样的 kc_ids（校验通过）。

    Raises:
        PathBuildError: 存在意图定性但无 rubric 的 KC，`.missing` 为完整清单。
    """
    intent_set = frozenset(intent) if intent is not None else None

    missing: list[str] = []
    for kc in kc_ids:
        want_qualitative = (
            kc in intent_set
            if intent_set is not None
            else await gate_store.has_intent(db, kc)
        )
        if want_qualitative and not await gate_store.has_rubric(db, kc):
            missing.append(kc)

    if missing:
        raise PathBuildError(missing)
    return list(kc_ids)
