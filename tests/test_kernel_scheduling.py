"""内核调度/掌握度边界单元测试（无 DB，纯函数）。

覆盖：
- 集中练习去抖（item 6）：同日重复作答不推进 FSRS 调度，但掌握度仍更新；
  默认 min_review_interval_hours=0 时行为不变（仍推进）。
- P(L) 下界红线（item 15）：掌握度严格 >0。
"""
from datetime import datetime, timedelta, timezone

from oskill.cognitive_state import cognitive_update, CognitiveUpdateInput
from obase.cognitive_types import new_state_from_prior as bkt_new_state
from oprim.fsrs_engine import fsrs_new_card

_NOW = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
_PRIOR = {"p_init": 0.2, "p_transit": 0.2, "p_guess": 0.15, "p_slip": 0.12}


def _first_review(now=_NOW, debounce=20.0):
    state = bkt_new_state(kc_id="GDMATH-X", prior=_PRIOR)
    card = fsrs_new_card()
    r = cognitive_update(input=CognitiveUpdateInput(
        state=state, card_dict=card, is_correct=True,
        min_review_interval_hours=debounce, now=now,
    ))
    return r


def test_massed_practice_debounce_holds_schedule():
    r1 = _first_review()                         # 新卡片：首答建立调度
    due1 = r1.card_dict.get("due")
    last1 = r1.card_dict.get("last_review")
    n1 = r1.state.n_attempts
    assert last1 is not None                     # 首答确实推进了调度

    # 2 小时后再答（集中练习）：调度不应推进
    now2 = _NOW + timedelta(hours=2)
    r2 = cognitive_update(input=CognitiveUpdateInput(
        state=r1.state, card_dict=r1.card_dict, is_correct=True,
        min_review_interval_hours=20.0, now=now2,
    ))
    assert r2.card_dict.get("due") == due1            # due 未变
    assert r2.card_dict.get("last_review") == last1   # last_review 未变
    assert r2.state.n_attempts == n1 + 1              # 但掌握度/计数仍更新


def test_default_zero_threshold_still_advances():
    """默认 min_review_interval_hours=0：同日重复仍推进调度（行为不变）。"""
    r1 = _first_review(debounce=0.0)
    last1 = r1.card_dict.get("last_review")
    now2 = _NOW + timedelta(hours=2)
    r2 = cognitive_update(input=CognitiveUpdateInput(
        state=r1.state, card_dict=r1.card_dict, is_correct=True,
        min_review_interval_hours=0.0, now=now2,
    ))
    assert r2.card_dict.get("last_review") != last1   # 推进了


def test_next_day_review_advances_despite_debounce():
    """次日复习（>20h）即使开启去抖也照常推进调度。"""
    r1 = _first_review()
    last1 = r1.card_dict.get("last_review")
    now2 = _NOW + timedelta(hours=25)
    r2 = cognitive_update(input=CognitiveUpdateInput(
        state=r1.state, card_dict=r1.card_dict, is_correct=True,
        min_review_interval_hours=20.0, now=now2,
    ))
    assert r2.card_dict.get("last_review") != last1


def test_fsrs_parameters_change_scheduling():
    """个性化基础设施：自定义 FSRS 权重改变调度（默认 None 行为不变）。"""
    from fsrs import Rating, Scheduler
    from oprim.fsrs_engine import fsrs_new_card, fsrs_review
    now = _NOW
    default = tuple(Scheduler().parameters)
    perturbed = tuple(p * 1.05 for p in default)  # 小幅扰动，保持在 FSRS 合法区间内
    card = fsrs_new_card()
    d1 = fsrs_review(card_dict=card, rating=Rating.Good, now=now)            # 默认
    d2 = fsrs_review(card_dict=card, rating=Rating.Good, now=now, parameters=perturbed)
    # 不同权重 → 不同稳定性/到期
    assert d1.get("stability") != d2.get("stability") or d1.get("due") != d2.get("due")
    # 默认显式传 None == 不传
    d3 = fsrs_review(card_dict=card, rating=Rating.Good, now=now, parameters=None)
    assert d3.get("due") == d1.get("due")


def test_due_compute_unified_semantics():
    """item 13：missing due → 不到期；已排程且过期 → 到期。"""
    from oprim.due_compute import due_compute
    now = _NOW
    assert due_compute(card_dict={}, now=now) is False               # 未排程
    assert due_compute(card_dict={"due": None}, now=now) is False
    past = (now - timedelta(days=1)).isoformat()
    future = (now + timedelta(days=1)).isoformat()
    assert due_compute(card_dict={"due": past}, now=now) is True      # 已过期
    assert due_compute(card_dict={"due": future}, now=now) is False   # 未到期
    assert due_compute(card_dict={"due": "garbage"}, now=now) is False


def test_pl_floor_strictly_positive():
    """P(L) 下界红线：连续答错也不把掌握度压到 0/负。"""
    state = bkt_new_state(kc_id="GDMATH-X", prior=_PRIOR)
    card = fsrs_new_card()
    now = _NOW
    for i in range(30):
        r = cognitive_update(input=CognitiveUpdateInput(
            state=state, card_dict=card, is_correct=False, now=now + timedelta(days=i),
        ))
        state, card = r.state, r.card_dict
        assert state.p_mastery > 0.0
        assert state.p_mastery <= 0.97
