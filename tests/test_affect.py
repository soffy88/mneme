"""情感感知（教育理念 08）纯函数。行为信号 → 情感态 + 自适应建议。"""

from oprim.affect import affect_estimate


def test_frustrated_on_consecutive_wrong():
    e = affect_estimate(consecutive_wrong=3)
    assert e["state"] == "frustrated"


def test_frustrated_on_high_giveup():
    assert affect_estimate(give_up_rate=0.6)["state"] == "frustrated"


def test_disengaged_on_high_reveal():
    e = affect_estimate(reveal_rate=0.6)
    assert e["state"] == "disengaged"


def test_flow_on_fast_correct_streak():
    e = affect_estimate(recent_correct_streak=6, fast_correct=True)
    assert e["state"] == "flow"
    assert e["adaptation"] == "raise_challenge"


def test_neutral_default():
    assert affect_estimate()["state"] == "neutral"


def test_frustrated_takes_priority_over_flow():
    # 连错优先于其它信号
    assert (
        affect_estimate(
            consecutive_wrong=4, recent_correct_streak=6, fast_correct=True
        )["state"]
        == "frustrated"
    )
