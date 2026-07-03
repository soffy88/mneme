"""T.5 单测：oskill fire_propagate（FIRe-lite 前置信用回写计算，Master §4.8）。

覆盖：κ 计算、τ 截断、due 只顺延不提前、max(due_p, now+κ·S) 语义、
输入 card 只读（D/S/R 逐位不动）、未排程/无稳定性跳过。
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

from oskill.fire_propagate import FirePrereq, FireOutcome, fire_propagate

NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


def _card(*, stability: float, due: datetime, last_review: datetime) -> dict:
    return {
        "card_id": 1,
        "state": 2,
        "step": None,
        "stability": stability,
        "difficulty": 5.0,
        "due": due.isoformat(),
        "last_review": last_review.isoformat(),
    }


def test_kappa_is_kappa0_times_p_mastery():
    """κ_p = κ0 · P(L)_p（乘掌握度而非缺口——保守化，防信号污染）。"""
    card = _card(
        stability=10.0, due=NOW + timedelta(days=2), last_review=NOW - timedelta(days=5)
    )
    out = fire_propagate(
        trigger_kc_id="c",
        prereqs=[FirePrereq(kc_id="p", p_mastery=0.8, card_dict=card)],
        now=NOW,
        kappa0=0.5,
        tau=0.3,
    )
    assert len(out) == 1
    assert out[0].kappa == 0.4  # 0.5 × 0.8


def test_tau_cutoff_no_writeback():
    """κ_p < τ 不回写：掌握度低者可能被绕过/蒙对，不免除复习。"""
    card = _card(
        stability=10.0, due=NOW + timedelta(days=1), last_review=NOW - timedelta(days=5)
    )
    out = fire_propagate(
        trigger_kc_id="c",
        prereqs=[FirePrereq(kc_id="p", p_mastery=0.5, card_dict=card)],  # κ=0.25<0.3
        now=NOW,
    )
    assert out[0].new_due is None
    assert out[0].skip_reason == "kappa_below_tau"
    # 边界：κ=τ 恰好回写
    out2 = fire_propagate(
        trigger_kc_id="c",
        prereqs=[FirePrereq(kc_id="p", p_mastery=0.6, card_dict=card)],  # κ=0.3
        now=NOW,
    )
    assert out2[0].new_due is not None


def test_new_due_is_max_semantics():
    """new_due = max(due_p, now + κ·S 天)：候选晚于原 due 才顺延到候选。"""
    s = 10.0
    kappa = 0.5 * 0.9  # 0.45 → 候选 = now + 4.5 天
    due = NOW + timedelta(days=2)
    card = _card(stability=s, due=due, last_review=NOW - timedelta(days=5))
    out = fire_propagate(
        trigger_kc_id="c",
        prereqs=[FirePrereq(kc_id="p", p_mastery=0.9, card_dict=card)],
        now=NOW,
    )
    expected = NOW + timedelta(days=kappa * s)
    assert out[0].new_due == expected.isoformat()
    assert out[0].due_before == due.isoformat()


def test_due_only_postponed_never_advanced():
    """只顺延不提前：原 due 已晚于候选 → max 取原 due，无净顺延，不回写。"""
    due = NOW + timedelta(days=20)  # 候选 = now + 0.45×10 = 4.5 天 < 20 天
    card = _card(stability=10.0, due=due, last_review=NOW - timedelta(days=5))
    out = fire_propagate(
        trigger_kc_id="c",
        prereqs=[FirePrereq(kc_id="p", p_mastery=0.9, card_dict=card)],
        now=NOW,
    )
    assert out[0].new_due is None
    assert out[0].skip_reason == "no_net_postpone"


def test_overdue_card_postponed_from_now():
    """已到期卡（due<now）：max(due, now+κS) = now+κS，从此刻起顺延。"""
    due = NOW - timedelta(days=3)
    card = _card(stability=10.0, due=due, last_review=NOW - timedelta(days=10))
    out = fire_propagate(
        trigger_kc_id="c",
        prereqs=[FirePrereq(kc_id="p", p_mastery=0.9, card_dict=card)],
        now=NOW,
    )
    assert out[0].was_due is True
    assert out[0].new_due == (NOW + timedelta(days=0.45 * 10.0)).isoformat()


def test_input_card_not_mutated_dsr_untouched():
    """纯函数：输入 card 只读，D/S/R 逐位不动（红线：不改记忆状态）。"""
    card = _card(
        stability=7.7, due=NOW + timedelta(days=1), last_review=NOW - timedelta(days=4)
    )
    snapshot = copy.deepcopy(card)
    fire_propagate(
        trigger_kc_id="c",
        prereqs=[FirePrereq(kc_id="p", p_mastery=0.95, card_dict=card)],
        now=NOW,
    )
    assert card == snapshot


def test_unscheduled_or_no_stability_skipped():
    """无 due（未排程）或无 stability 的卡不回写。"""
    no_due = {
        "card_id": 1,
        "state": 1,
        "step": 0,
        "stability": None,
        "difficulty": None,
        "due": None,
        "last_review": None,
    }
    out = fire_propagate(
        trigger_kc_id="c",
        prereqs=[FirePrereq(kc_id="p", p_mastery=0.9, card_dict=no_due)],
        now=NOW,
    )
    assert out[0].new_due is None

    no_s = _card(
        stability=1.0, due=NOW + timedelta(days=1), last_review=NOW - timedelta(days=1)
    )
    no_s["stability"] = None
    out2 = fire_propagate(
        trigger_kc_id="c",
        prereqs=[FirePrereq(kc_id="p", p_mastery=0.9, card_dict=no_s)],
        now=NOW,
    )
    assert out2[0].new_due is None
    assert out2[0].skip_reason == "no_stability"


def test_multiple_prereqs_one_outcome_each():
    """结果与输入前置一一对应。"""
    card = _card(
        stability=10.0, due=NOW + timedelta(days=1), last_review=NOW - timedelta(days=5)
    )
    out = fire_propagate(
        trigger_kc_id="c",
        prereqs=[
            FirePrereq(kc_id="p1", p_mastery=0.9, card_dict=card),
            FirePrereq(kc_id="p2", p_mastery=0.1, card_dict=card),
        ],
        now=NOW,
    )
    assert [o.kc_id for o in out] == ["p1", "p2"]
    assert isinstance(out[0], FireOutcome)
    assert out[0].new_due is not None and out[1].new_due is None
