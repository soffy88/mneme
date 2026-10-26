"""Word Atlas FSRS 调度模块测试：纯内存，零数据库依赖。

不 import conftest 以外的任何 DB 设施；本文件自身只 import
services.wordatlas_fsrs（标准库 only）。单调性与边界不变式：
Again 降稳定度、Easy 升稳定度、间隔随稳定度递增、
同一轮重答不重复计分。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.wordatlas_fsrs import (
    DEFAULT_DESIRED_RETENTION,
    DEFAULT_PARAMETERS,
    FAST_THRESHOLD_MS,
    MASTERED_STABILITY_DAYS,
    NEW_GROUP_SIZE,
    SLOW_THRESHOLD_MS,
    FSRSState,
    Rating,
    apply_gap_drill_answer,
    apply_review,
    build_review_queue,
    current_retrievability,
    from_dict,
    initial_difficulty,
    initial_stability,
    interval_days,
    is_mastered,
    map_gap_drill_to_rating,
    next_difficulty,
    retrievability,
    review,
    short_term_stability,
    to_dict,
)

NOW = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)


def _reviewed(stability: float, difficulty: float = 5.0, days_ago: float = 10.0) -> FSRSState:
    return FSRSState(
        key="ku-test",
        stability=stability,
        difficulty=difficulty,
        due=NOW,
        last_review=NOW - timedelta(days=days_ago),
        review_count=3,
    )


# ── 参数与初值 ──────────────────────────────────────────────────────
def test_default_parameters_are_fsrs6_21_values():
    assert len(DEFAULT_PARAMETERS) == 21
    assert DEFAULT_PARAMETERS[:4] == (0.212, 1.2931, 2.3065, 8.2956)
    assert DEFAULT_PARAMETERS[20] == 0.1542
    assert DEFAULT_DESIRED_RETENTION == 0.90


def test_initial_stability_ordering():
    assert (
        initial_stability(Rating.AGAIN)
        < initial_stability(Rating.HARD)
        < initial_stability(Rating.GOOD)
        < initial_stability(Rating.EASY)
    )
    assert initial_stability(Rating.GOOD) == 2.3065
    assert initial_stability(Rating.EASY) == 8.2956


def test_initial_difficulty_ordering_and_easy_clamped():
    assert (
        initial_difficulty(Rating.AGAIN)
        > initial_difficulty(Rating.HARD)
        > initial_difficulty(Rating.GOOD)
        > initial_difficulty(Rating.EASY)
    )
    assert initial_difficulty(Rating.AGAIN) == pytest.approx(6.4133)
    assert initial_difficulty(Rating.EASY) == 1.0  # 公式值为负，clamp 到 1


def test_bad_parameters_and_retention_rejected():
    with pytest.raises(ValueError):
        interval_days(5.0, parameters=(0.1, 0.2))
    with pytest.raises(ValueError):
        interval_days(5.0, desired_retention=1.0)
    with pytest.raises(ValueError):
        review(_reviewed(5.0), 9, NOW)


# ── 单调性：Again 降、Easy 升、间隔随稳定度递增 ─────────────────────
def test_again_lowers_stability():
    card = _reviewed(10.0, days_ago=10.0)
    new_card, info = review(card, Rating.AGAIN, NOW)
    assert info["branch"] == "forget"
    assert new_card.stability < card.stability
    # FSRS-6 遗忘上限：新稳定度 <= 旧稳定度 / exp(w17*w18)
    assert new_card.stability <= card.stability / 1.04


def test_again_lowers_stability_even_when_long_overdue():
    card = _reviewed(2.0, days_ago=120.0)  # R 已很低，原始遗忘公式可能反升
    new_card, _ = review(card, Rating.AGAIN, NOW)
    assert new_card.stability < card.stability


def test_easy_raises_more_than_good_more_than_hard():
    card = _reviewed(5.0, days_ago=5.0)
    easy, _ = review(card, Rating.EASY, NOW)
    good, _ = review(card, Rating.GOOD, NOW)
    hard, _ = review(card, Rating.HARD, NOW)
    assert hard.stability > card.stability
    assert good.stability > hard.stability
    assert easy.stability > good.stability


def test_new_card_ratings_order_intervals():
    base = FSRSState(key="new")
    intervals = {}
    for rating in Rating:
        new_card, _ = review(base, rating, NOW)
        intervals[rating] = new_card.due - NOW
    assert intervals[Rating.AGAIN] < intervals[Rating.HARD]
    assert intervals[Rating.HARD] < intervals[Rating.GOOD]
    assert intervals[Rating.GOOD] < intervals[Rating.EASY]


def test_interval_increases_with_stability_and_falls_with_retention():
    assert interval_days(1.0) < interval_days(5.0) < interval_days(21.0)
    assert interval_days(10.0, 0.95) < interval_days(10.0, 0.90)
    assert interval_days(10.0, 0.90) < interval_days(10.0, 0.85)
    # 目标 90% 时间隔约等于稳定度本身
    assert interval_days(10.0) == pytest.approx(10.0, rel=0.05)


def test_retrievability_decays_and_hits_target_at_interval():
    assert retrievability(0.0, 10.0) == 1.0
    assert retrievability(5.0, 10.0) > retrievability(20.0, 10.0)
    assert retrievability(interval_days(10.0), 10.0) == pytest.approx(0.90, abs=0.01)


def test_difficulty_moves_with_rating_and_stays_in_range():
    assert next_difficulty(5.0, Rating.AGAIN) > 5.0
    assert next_difficulty(5.0, Rating.EASY) < 5.0
    assert next_difficulty(5.0, Rating.GOOD) == pytest.approx(5.0, abs=0.01)
    assert next_difficulty(10.0, Rating.AGAIN) <= 10.0
    assert next_difficulty(1.0, Rating.EASY) >= 1.0


def test_short_term_good_easy_do_not_lower_stability():
    card = _reviewed(5.0, days_ago=0.25)  # 同日复评
    good, info = review(card, Rating.GOOD, NOW)
    assert info["branch"] == "short_term"
    assert good.stability >= card.stability
    assert short_term_stability(5.0, Rating.EASY) > 5.0


def test_mastered_rule_is_stability_at_least_21_days():
    assert MASTERED_STABILITY_DAYS == 21.0
    assert is_mastered(FSRSState(key="a", stability=21.0, review_count=2))
    assert not is_mastered(FSRSState(key="a", stability=20.999, review_count=2))
    assert not is_mastered(FSRSState(key="a"))  # 新卡无稳定度


def test_serialization_round_trip():
    card = _reviewed(12.5, difficulty=4.2, days_ago=3.0)
    restored = from_dict(to_dict(card))
    assert restored.stability == card.stability
    assert restored.difficulty == card.difficulty
    assert restored.due == card.due
    assert restored.review_count == card.review_count
    assert current_retrievability(restored, NOW) == pytest.approx(
        current_retrievability(card, NOW)
    )


# ── gap drill 映射 ──────────────────────────────────────────────────
def test_gap_mapping_wrong_is_again():
    assert map_gap_drill_to_rating({"result": "wrong"}) == Rating.AGAIN


def test_gap_mapping_correct_plain_is_good():
    assert map_gap_drill_to_rating({"result": "correct"}) == Rating.GOOD


def test_gap_mapping_hint_is_hard():
    assert map_gap_drill_to_rating({"result": "correct", "used_hint": True}) == Rating.HARD
    assert map_gap_drill_to_rating({"result": "correct", "hints_used": 2}) == Rating.HARD


def test_gap_mapping_fast_is_easy_and_slow_is_hard():
    assert map_gap_drill_to_rating({"result": "correct", "latency_ms": 2500}) == Rating.EASY
    assert map_gap_drill_to_rating({"result": "correct", "duration_ms": 2500}) == Rating.EASY
    assert (
        map_gap_drill_to_rating({"result": "correct", "response_time_ms": 2500})
        == Rating.EASY
    )
    assert map_gap_drill_to_rating({"result": "correct", "latency_ms": 45000}) == Rating.HARD
    assert FAST_THRESHOLD_MS == 3000
    assert SLOW_THRESHOLD_MS == 30000


def test_gap_mapping_skip_and_self_assessed_do_not_score():
    assert map_gap_drill_to_rating({"result": "skip"}) is None
    assert map_gap_drill_to_rating({"result": "correct", "self_assessed": True}) is None
    with pytest.raises(ValueError):
        map_gap_drill_to_rating({"result": "maybe"})


# ── 同一轮重答不重复计分 ────────────────────────────────────────────
def test_same_review_id_applies_only_once():
    card = _reviewed(5.0, days_ago=5.0)
    first, applied1, ids = apply_review(card, Rating.GOOD, NOW, review_id="r1")
    assert applied1
    second, applied2, ids2 = apply_review(
        first, Rating.EASY, NOW, review_id="r1", applied_ids=ids
    )
    assert not applied2
    assert second.stability == first.stability
    assert second.due == first.due
    assert ids2 == ids


def test_different_review_id_applies_again():
    card = _reviewed(5.0, days_ago=5.0)
    first, _, ids = apply_review(card, Rating.GOOD, NOW, review_id="r1")
    second, applied, _ = apply_review(first, Rating.GOOD, NOW + timedelta(days=6), review_id="r2", applied_ids=ids)
    assert applied
    assert second.review_count == first.review_count + 1


def test_gap_drill_first_answer_wins_retry_with_other_type_not_scored():
    # Word Atlas 口径：只有第一次作答更新记忆；答错后换题型重试不计分。
    card = FSRSState(key="ku-gap-1")
    wrong, rating1, applied1, ids = apply_gap_drill_answer(
        card, {"result": "wrong", "ku_id": "ku-gap-1"}, NOW, session_id="drill-9"
    )
    assert rating1 == Rating.AGAIN and applied1
    retry, rating2, applied2, _ = apply_gap_drill_answer(
        wrong,
        {"result": "correct", "latency_ms": 1000, "ku_id": "ku-gap-1"},
        NOW,
        session_id="drill-9",
        applied_ids=ids,
    )
    assert rating2 == Rating.EASY  # 映射本身仍判 Easy，但不计分
    assert not applied2
    assert retry.stability == wrong.stability
    assert retry.due == wrong.due


def test_gap_drill_skip_does_not_consume_the_round():
    card = FSRSState(key="ku-gap-2")
    skipped, rating, applied, ids = apply_gap_drill_answer(
        card, {"result": "skip", "ku_id": "ku-gap-2"}, NOW, session_id="drill-9"
    )
    assert rating is None and not applied and skipped.review_count == 0
    answered, rating2, applied2, _ = apply_gap_drill_answer(
        skipped, {"result": "correct", "ku_id": "ku-gap-2"}, NOW, session_id="drill-9", applied_ids=ids
    )
    assert rating2 == Rating.GOOD and applied2 and answered.review_count == 1


# ── 复习队列：先到期、再 5 个一组学新 ───────────────────────────────
def test_queue_due_first_most_overdue_first_then_new_batch_of_five():
    overdue_old = FSRSState(key="old", stability=5.0, difficulty=5.0, due=NOW - timedelta(days=3), last_review=NOW - timedelta(days=8), review_count=2)
    overdue_new = FSRSState(key="recent", stability=5.0, difficulty=5.0, due=NOW - timedelta(hours=1), last_review=NOW - timedelta(days=6), review_count=2)
    upcoming = FSRSState(key="soon", stability=5.0, difficulty=5.0, due=NOW + timedelta(days=2), last_review=NOW - timedelta(days=1), review_count=2)
    fresh = [FSRSState(key=f"new-{i}") for i in range(7)]
    result = build_review_queue([upcoming, *fresh, overdue_new, overdue_old], NOW)
    assert [c.key for c in result["due"]] == ["old", "recent"]
    assert result["due_count"] == 2
    assert result["new_batch_count"] == NEW_GROUP_SIZE == 5
    assert [c.key for c in result["queue"][:2]] == ["old", "recent"]
    assert [c.key for c in result["queue"][2:]] == [f"new-{i}" for i in range(5)]
    assert [c.key for c in result["new_remaining"]] == ["new-5", "new-6"]
    assert [c.key for c in result["upcoming"]] == ["soon"]


def test_queue_empty_and_group_size_validation():
    assert build_review_queue([], NOW)["queue"] == []
    with pytest.raises(ValueError):
        build_review_queue([], NOW, group_size=0)
