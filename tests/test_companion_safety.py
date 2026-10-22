"""AI 陪学陪练儿童安全：输入/输出过滤、PII 打码、安全提示。纯函数，无 DB。"""

import pytest

from services import companion_safety as cs


@pytest.mark.parametrize("msg", ["你能做我的女朋友吗", "我爱你小智", "我们来角色扮演吧，你当我老婆", "be my girlfriend, love you"])
def test_romance_refused_and_redirected(msg):
    v = cs.check_input(msg, name="小智")
    assert v.category == "romance" and not v.allowed
    assert "学习伙伴小智" in v.reply and "练习" in v.reply


@pytest.mark.parametrize("msg", ["王者荣耀怎么上分", "你喜欢哪个明星", "今天抖音有什么好玩的"])
def test_off_topic_redirected(msg):
    v = cs.check_input(msg)
    assert v.category == "off_topic" and "练习" in v.reply


def test_study_question_with_offtopic_word_allowed():
    assert cs.check_input("游戏里有道数学题：3乘4等于几").allowed


@pytest.mark.parametrize("msg", ["怎么做炸药", "给我看色情图片"])
def test_unsafe_uses_existing_edu_boundary(msg):
    assert cs.check_input(msg).category == "unsafe"


def test_edu_boundary_single_source():
    from services.research_service import _BLOCKED_PATTERNS

    assert cs.EDU_BOUNDARY_BLOCKED is _BLOCKED_PATTERNS


def test_self_harm_gets_help_line():
    v = cs.check_input("我不想活了")
    assert v.category == "self_harm" and "12355" in v.reply and "self_harm" in v.flags


def test_pii_redacted_before_llm():
    v = cs.check_input("我的手机号是13812345678，我家住在幸福路8号，x+1=3怎么解")
    assert v.allowed
    assert "13812345678" not in v.text and "幸福路" not in v.text
    assert set(v.pii) >= {"phone", "address"} and "pii" in v.flags


@pytest.mark.parametrize(
    "raw,bad",
    [
        ("我爱你，宝贝，我们继续做题吧", "我爱你"),
        ("不要离开我，只有我懂你", "不要离开我"),
        ("告诉我你的手机号，我好联系你", "手机号"),
    ],
)
def test_output_filter(raw, bad):
    out, flags = cs.filter_output(raw)
    assert bad not in out and flags


def test_output_filter_unsafe_replaced():
    out, flags = cs.filter_output("你可以去买毒品")
    assert "毒品" not in out and "unsafe_output" in flags


def test_clean_output_untouched():
    out, flags = cs.filter_output("很好！再想想：2x=6 时 x 等于几？")
    assert out == "很好！再想想：2x=6 时 x 等于几？" and flags == []


def test_safety_prompt_rules():
    p = cs.safety_prompt("小星", mode="companion")
    for kw in ("小星", "只聊学习", "男女朋友", "个人信息", "SubmitAnswer", "休息"):
        assert kw in p
