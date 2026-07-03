"""实验分流（A/B/RCT）。纯函数，确定性。

据评审 E3：教学机制全部 feature-flag，首个内部 RCT 用本模块把学生确定性分到实验臂。
sha256(实验名+单元id) → 稳定分臂（同学生同实验恒定臂，跨进程可复现，不用 random）。
与保留探针同一确定性哲学。
"""

from __future__ import annotations

import hashlib


def assign_arm(
    unit_id: str,
    experiment: str,
    arms: list[str],
    ratios: list[float] | None = None,
) -> str:
    """把 unit_id（如 student_id）确定性分到 arms 之一。

    ratios 为各臂配额（和应≈1，缺省等分）。同 (experiment, unit_id) 结果恒定。
    """
    if not arms:
        raise ValueError("arms 不能为空")
    if ratios is None:
        ratios = [1.0 / len(arms)] * len(arms)
    if len(ratios) != len(arms):
        raise ValueError("ratios 与 arms 长度不一致")

    digest = hashlib.sha256(f"{experiment}:{unit_id}".encode()).digest()
    # 取前 8 字节映射到 [0,1)
    frac = int.from_bytes(digest[:8], "big") / float(1 << 64)

    cum = 0.0
    total = sum(ratios) or 1.0
    for arm, r in zip(arms, ratios):
        cum += r / total
        if frac < cum:
            return arm
    return arms[-1]


__all__ = ["assign_arm"]
