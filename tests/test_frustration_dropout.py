"""挫败流失会话埋点(纯函数)：连≥3错为挫败，末尾挫败且此后≥7天无活动=流失。"""

from datetime import datetime, timedelta, timezone

from services.experiment_service import frustration_dropout_for_student

NOW = datetime(2026, 7, 3, tzinfo=timezone.utc)


def _ev(is_correct, days_ago):
    return (is_correct, NOW - timedelta(days=days_ago))


def test_no_events():
    r = frustration_dropout_for_student([], NOW)
    assert r["had_frustration"] is False and r["dropped"] is False


def test_dropped_frustrated_tail_and_inactive():
    # 末尾连 3 错，最后活动 8 天前 → 挫败流失
    ev = [_ev(True, 12), _ev(False, 10), _ev(False, 9), _ev(False, 8)]
    r = frustration_dropout_for_student(ev, NOW)
    assert r["had_frustration"] is True and r["dropped"] is True


def test_recovered_not_dropped():
    # 连 3 错后又做对(回来了)，末尾非挫败 → 有挫败但未流失
    ev = [_ev(False, 10), _ev(False, 9), _ev(False, 8), _ev(True, 7)]
    r = frustration_dropout_for_student(ev, NOW)
    assert r["had_frustration"] is True and r["dropped"] is False


def test_frustrated_but_still_active_not_dropped():
    # 末尾连 3 错，但昨天还在活动(<7天) → 未流失
    ev = [_ev(False, 3), _ev(False, 2), _ev(False, 1)]
    r = frustration_dropout_for_student(ev, NOW)
    assert r["had_frustration"] is True and r["dropped"] is False


def test_under_run_not_frustrated():
    # 只连 2 错 → 未达挫败集
    ev = [_ev(True, 10), _ev(False, 9), _ev(False, 8)]
    r = frustration_dropout_for_student(ev, NOW)
    assert r["had_frustration"] is False and r["dropped"] is False
