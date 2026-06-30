"""P0-2 识别维度 (M-G §4.5) 回归：交错情境才更新 p_recognition，做对↑做错↓，单KC不动。"""
from datetime import datetime, timezone

import pytest

from oskill.cognitive_state import cognitive_update, CognitiveUpdateInput
from obase.cognitive_types import KCState, fsrs_new_card


def _state(p_recognition=0.20):
    return KCState(
        kc_id="GDMATH-TEST",
        p_mastery=0.5,
        p_init=0.3,
        p_transit=0.2,
        p_guess=0.2,
        p_slip=0.1,
        p_recognition=p_recognition,
        p_recognition_init=0.20,
        long_term_mastery=0.5,
        n_attempts=0,
    )


def _run(is_interleaved, is_correct, p_rec0=0.20):
    st = _state(p_rec0)
    card = fsrs_new_card()
    card_dict = card if isinstance(card, dict) else card.__dict__
    res = cognitive_update(input=CognitiveUpdateInput(
        state=st, card_dict=card_dict, is_correct=is_correct,
        is_interleaved=is_interleaved, now=datetime.now(timezone.utc),
    ))
    return res.state.p_recognition


def test_interleaved_correct_raises_recognition():
    assert _run(is_interleaved=True, is_correct=True) > 0.20


def test_interleaved_wrong_lowers_recognition():
    assert _run(is_interleaved=True, is_correct=False) < 0.20


def test_non_interleaved_does_not_change_recognition():
    # 单 KC 专项：只提升 mastery，不动 recognition
    assert _run(is_interleaved=False, is_correct=True) == pytest.approx(0.20)
    assert _run(is_interleaved=False, is_correct=False) == pytest.approx(0.20)


def test_recognition_capped_at_097():
    # 连续交错做对不应超过 0.97（与 mastery 同封顶，算法红线）
    st = _state(0.96)
    card = fsrs_new_card()
    card_dict = card if isinstance(card, dict) else card.__dict__
    pr = 0.96
    for _ in range(20):
        res = cognitive_update(input=CognitiveUpdateInput(
            state=st, card_dict=card_dict, is_correct=True,
            is_interleaved=True, now=datetime.now(timezone.utc),
        ))
        pr = res.state.p_recognition
    assert pr <= 0.97
