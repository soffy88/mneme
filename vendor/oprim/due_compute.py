"""FSRS 到期判定能力

FSRS 状态 → 到期判定
"""

from datetime import datetime, timezone
from typing import Optional

def due_compute(*, card_dict: dict, now: Optional[datetime] = None) -> bool:
    """计算 FSRS Card 是否已到期。

    Parameters
    ----------
    card_dict : dict
        FSRS Card 的字典表示。
    now : datetime | None
        当前时间（UTC），默认使用当前时间。
        
    Returns
    -------
    bool
        卡片已到期（已排程且 due <= now）返回 True；未设置 due（未排程/新卡片）返回 False。

    Note
    ----
    单源到期语义（item 13）：missing due → 未排程 → **不到期**。复习池只收"已学过且到期"
    的卡片；从未排程的新卡片由新学路径处理，不应混进复习池（与 review_queue_workflow 一致）。
    """
    due_iso = card_dict.get("due")
    if not due_iso:
        return False

    try:
        if hasattr(due_iso, "isoformat"):
            due_dt = due_iso
        else:
            # 兼容 python 3.11 以前如果 Z 不带冒号可能出错，但这里假定标准 ISO
            due_dt = datetime.fromisoformat(due_iso.replace('Z', '+00:00'))
    except ValueError:
        return False  # 无法解析的 due 视为未排程（不混入复习池）

    now = now or datetime.now(timezone.utc)
    return now >= due_dt
