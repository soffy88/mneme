"""成长型思维反馈框架（教育理念 05·Dweck）。纯函数。"""

from oprim.growth_feedback import growth_message


def test_correct_with_struggle_praises_persistence():
    m = growth_message(is_correct=True, struggled=True)
    assert "吃力但做对" in m  # 表扬坚持/努力，非"聪明"
    assert "聪明" not in m


def test_correct_praises_strategy_not_ability():
    m = growth_message(is_correct=True, struggled=False)
    assert "方法" in m or "节奏" in m
    assert "聪明" not in m


def test_careless_attributes_to_changeable_strategy():
    m = growth_message(is_correct=False, error_type="careless")
    assert "细心" in m
    assert "不是能力" in m  # 归因于可改变的策略而非能力


def test_dontknow_uses_not_yet_framing():
    m = growth_message(is_correct=False, error_type="dontknow")
    assert "还没" in m  # not yet 文化


def test_generic_wrong_normalizes_error():
    m = growth_message(is_correct=False, error_type=None)
    assert "错误是学习的一部分" in m  # 错误正常化


def test_never_praises_intelligence():
    for ic in (True, False):
        for et in (None, "careless", "dontknow"):
            for st in (True, False):
                assert "聪明" not in growth_message(
                    is_correct=ic, error_type=et, struggled=st
                )
