"""P2: cognitive_update 纯函数黄金样例（无 DB）——掌握度算对的契约锁。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from obase.cognitive_types import fsrs_new_card, new_state_from_prior
from oskill.cognitive_state import CognitiveUpdateInput, cognitive_update


def _state(kc: str = "GDMATH-SET-01", **prior_overrides):
    prior = {
        "p_init": 0.3,
        "p_transit": 0.2,
        "p_guess": 0.2,
        "p_slip": 0.1,
        **prior_overrides,
    }
    return new_state_from_prior(kc_id=kc, prior=prior)


def test_correct_answers_raise_mastery_monotone():
    state = _state()
    card = fsrs_new_card()
    now = datetime.now(timezone.utc)
    seq = []
    for i in range(8):
        out = cognitive_update(
            input=CognitiveUpdateInput(
                state=state,
                card_dict=card,
                is_correct=True,
                now=now + timedelta(days=i),  # 跨天，避免 massed debounce 干扰
            )
        )
        state, card = out.state, out.card_dict
        seq.append(state.current())
    assert seq == sorted(seq), seq
    assert state.current() > 0.85
    assert all(0 < p <= 0.97 for p in seq)


def test_pl_never_exceeds_cap():
    state = _state(p_init=0.9, p_transit=0.5, p_slip=0.05, p_guess=0.05)
    card = fsrs_new_card()
    now = datetime.now(timezone.utc)
    for i in range(20):
        out = cognitive_update(
            input=CognitiveUpdateInput(
                state=state,
                card_dict=card,
                is_correct=True,
                now=now + timedelta(days=i),
            )
        )
        state, card = out.state, out.card_dict
    assert state.current() <= 0.97
    assert state.current() > 0.0


def test_high_mastery_error_weights_prefer_careless():
    """红线公式在「已掌握」状态上应偏好 careless（在 BKT 更新前判定）。

    注意：cognitive_update 的顺序是先 BKT 后 classify，一次答错会先把 P(L)
    拉低，因此 post-update 未必仍判粗心——这与 test_engine 的「先 classify
    再 update」场景不同。此处锁公式本身。
    """
    from oprim.bkt import classify_error

    state = _state(p_init=0.95, p_slip=0.1, p_guess=0.2)
    # 再抬一抬
    from oprim.bkt import bkt_update

    for _ in range(5):
        bkt_update(state=state, is_correct=True)
    assert state.current() > 0.9
    assert classify_error(state=state) == "careless"


def test_wrong_answer_always_sets_error_type():
    state = _state()
    card = fsrs_new_card()
    now = datetime.now(timezone.utc)
    out = cognitive_update(
        input=CognitiveUpdateInput(
            state=state,
            card_dict=card,
            is_correct=False,
            now=now,
        )
    )
    assert out.error_type in ("careless", "dontknow")
    out_ok = cognitive_update(
        input=CognitiveUpdateInput(
            state=out.state,
            card_dict=out.card_dict,
            is_correct=True,
            now=now + timedelta(days=1),
        )
    )
    assert out_ok.error_type is None


def test_low_mastery_wrong_classifies_dontknow():
    state = _state(p_init=0.1)
    card = fsrs_new_card()
    now = datetime.now(timezone.utc)
    out = cognitive_update(
        input=CognitiveUpdateInput(
            state=state,
            card_dict=card,
            is_correct=False,
            now=now,
        )
    )
    assert out.error_type == "dontknow"
    assert out.state.current() < 0.3


def test_massed_practice_debounce_skips_fsrs_schedule():
    """同日连答：掌握度更新，但 schedule_advanced=False 时 due 不推进。"""
    state = _state()
    card = fsrs_new_card()
    t0 = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    out1 = cognitive_update(
        input=CognitiveUpdateInput(
            state=state,
            card_dict=card,
            is_correct=True,
            now=t0,
            min_review_interval_hours=20.0,
        )
    )
    assert out1.schedule_advanced is True
    due1 = out1.card_dict.get("due") or out1.card_dict.get("due_date")
    # 1 小时后再答（集中练习）
    out2 = cognitive_update(
        input=CognitiveUpdateInput(
            state=out1.state,
            card_dict=out1.card_dict,
            is_correct=True,
            now=t0 + timedelta(hours=1),
            min_review_interval_hours=20.0,
        )
    )
    assert out2.schedule_advanced is False
    due2 = out2.card_dict.get("due") or out2.card_dict.get("due_date")
    assert due2 == due1
    # 掌握度仍应上升
    assert out2.state.current() >= out1.state.current()


def test_effective_mastery_is_long_term_times_R():
    state = _state()
    card = fsrs_new_card()
    now = datetime.now(timezone.utc)
    # 建一些 stability
    for i in range(5):
        out = cognitive_update(
            input=CognitiveUpdateInput(
                state=state,
                card_dict=card,
                is_correct=True,
                now=now + timedelta(days=i * 3),
            )
        )
        state, card = out.state, out.card_dict
    # 长期不练：R 衰减 → effective < long_term
    far = now + timedelta(days=60)
    out = cognitive_update(
        input=CognitiveUpdateInput(
            state=state,
            card_dict=card,
            is_correct=True,
            now=far,
        )
    )
    lt = out.state.long_term_mastery or out.state.current()
    assert 0 < out.effective_mastery <= lt + 1e-9


def test_interleaved_updates_recognition_only():
    state = _state()
    state.p_recognition = 0.2
    card = fsrs_new_card()
    now = datetime.now(timezone.utc)
    out = cognitive_update(
        input=CognitiveUpdateInput(
            state=state,
            card_dict=card,
            is_correct=True,
            is_interleaved=True,
            now=now,
        )
    )
    assert out.state.p_recognition is not None
    assert out.state.p_recognition > 0.2
