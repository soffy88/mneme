"""
FIRe-lite 前置复习信用回写计算（机制 M-H，Master §4.8）
========================================================
3O 范式：oskill/fire_propagate.py

成功解出综合题 = 隐式检索了其 verified 前置知识，按比例折算前置的复习信用，
**仅顺延 due**：new_due_p = max(due_p, now + κ_p × S_p 天)，κ_p = κ0 · P(L)_p。
不执行 FSRS review、不改 D/S/R、不更新 BKT——前置未被直接观测，只延后
"什么时候需要再看"。κ_p < τ 不回写（掌握度低者可能被绕过/蒙对，不免除复习）。

纯函数、stateless、不持久化；落库与事件追加由 omodul cognitive 事务负责。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from oprim.due_compute import due_compute
from oprim.fsrs_engine import fsrs_due_date, fsrs_retrievability


@dataclass(frozen=True)
class FirePrereq:
    """一个候选回写的前置知识点。

    Attributes
    ----------
    kc_id : str
    p_mastery : float
        该前置当前 BKT P(L)（掌握度）。
    card_dict : dict
        该前置当前 FSRS Card 字典（只读，不会被修改）。
    due : str | datetime | None
        可选的 due 覆盖；None 时从 card_dict 读取。
    """

    kc_id: str
    p_mastery: float
    card_dict: dict
    due: str | datetime | None = None


@dataclass(frozen=True)
class FireOutcome:
    """单个前置的回写计算结果。new_due=None 表示不回写（原因见 skip_reason）。"""

    kc_id: str
    kappa: float
    retrievability: Optional[float]
    was_due: bool
    due_before: Optional[str]
    new_due: Optional[str]
    skip_reason: Optional[str] = None


def _parse_dt(value: str | datetime) -> Optional[datetime]:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fire_propagate(
    *,
    trigger_kc_id: str,
    prereqs: list[FirePrereq],
    now: datetime,
    kappa0: float = 0.5,
    tau: float = 0.3,
) -> list[FireOutcome]:
    """FIRe-lite：对触发 KC 的各前置计算信用系数与顺延后的 due（纯计算）。

    Internal oprim composition:
    - oprim.fsrs_engine.fsrs_due_date       (读前置卡当前 due)
    - oprim.fsrs_engine.fsrs_retrievability (读前置卡当前 R，随结果记录供审计)
    - oprim.due_compute.due_compute         (前置卡此刻是否已到期，随结果记录)

    契约（Master §4.8）：
    - κ_p = κ0 · P(L)_p；κ_p < τ → 不回写。
    - new_due_p = max(due_p, now + κ_p × S_p 天)；只顺延不提前，无净顺延不回写。
    - 不触碰 card 的 D/S/R（输入 card_dict 只读）。

    Parameters
    ----------
    trigger_kc_id : str
        触发本次回写的（综合）KC——仅用于结果溯源，不参与计算。
    prereqs : list[FirePrereq]
        verified 前置列表（过滤 verified 边是调用方职责）。
    now : datetime
        触发交互时刻（UTC）。
    kappa0, tau : float
        信用系数基数（默认 0.5）与回写阈值（默认 0.3）。

    Returns
    -------
    list[FireOutcome]
        与输入前置一一对应；new_due 为 ISO 字符串或 None（不回写）。
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    outcomes: list[FireOutcome] = []
    for p in prereqs:
        kappa = round(kappa0 * float(p.p_mastery), 6)

        try:
            due_raw = (
                p.due if p.due is not None else fsrs_due_date(card_dict=p.card_dict)
            )
        except Exception:  # 无法解析的卡片视为未排程（不回写）
            due_raw = None
        due_dt = _parse_dt(due_raw) if due_raw is not None else None
        was_due = due_compute(card_dict=p.card_dict, now=now)
        due_before = due_dt.isoformat() if due_dt else None

        r: Optional[float]
        try:
            r = round(float(fsrs_retrievability(card_dict=p.card_dict, now=now)), 6)
        except Exception:
            r = None

        def _skip(reason: str) -> FireOutcome:
            return FireOutcome(
                kc_id=p.kc_id,
                kappa=kappa,
                retrievability=r,
                was_due=was_due,
                due_before=due_before,
                new_due=None,
                skip_reason=reason,
            )

        if kappa < tau:
            outcomes.append(_skip("kappa_below_tau"))
            continue
        if due_dt is None:
            outcomes.append(_skip("unscheduled"))
            continue
        stability = p.card_dict.get("stability")
        if not stability or float(stability) <= 0.0:
            outcomes.append(_skip("no_stability"))
            continue

        candidate = now + timedelta(days=kappa * float(stability))
        new_due = max(due_dt, candidate)
        if new_due <= due_dt:
            outcomes.append(_skip("no_net_postpone"))
            continue

        outcomes.append(
            FireOutcome(
                kc_id=p.kc_id,
                kappa=kappa,
                retrievability=r,
                was_due=was_due,
                due_before=due_before,
                new_due=new_due.isoformat(),
            )
        )
    return outcomes


__version__ = "0.1.0"
__manifest__ = {
    "version": __version__,
    "updated_at": "2026-07-02",
    "elements": [
        {
            "name": "fire_propagate",
            "layer": "oskill",
            "summary": "FIRe-lite 前置复习信用回写计算（只顺延 due）",
        },
    ],
}
