"""朗读文本规整：LaTeX → 口语中文、TTS 友好化、分句。纯函数，无 DB。"""

import pytest

from services.speech_text import latex_to_speech, split_sentences, tts_ready


@pytest.mark.parametrize(
    "src,want",
    [
        ("(a+b)^2", "a加b的平方"),
        ("$(a+b)^2$", "a加b的平方"),
        ("a²+b²=c²", "a的平方加b的平方等于c的平方"),
        (r"\frac{1}{2}+\frac{3}{4}", "2分之1加4分之3"),
        (r"x^{3}", "x的立方"),
        (r"2^{10}", "2的10次方"),
        (r"\sqrt{16}=4", "根号16等于4"),
        (r"\sqrt[3]{8}", "8的3次方根"),
        (r"3 \times 4 \div 2", "3乘4除以2"),
        ("-3+5=2", "负3加5等于2"),
        ("50%", "百分之50"),
        ("1/3", "3分之1"),
        (r"\angle A=90^\circ", "角A等于90度"),
        (r"x_1+x_2=-\frac{b}{a}", "x1加x2等于负a分之b"),
        (r"x \neq 0, x \geq 1", "x不等于0, x大于等于1"),
        (r"\sin \alpha", "正弦阿尔法"),
    ],
)
def test_latex_to_speech(src, want):
    assert latex_to_speech(src) == want


def test_tts_ready_spells_letters_and_strips_markdown():
    out = tts_ready("**解**：$(a+b)^2$")
    assert "*" not in out and "$" not in out
    assert out.endswith("诶加必的平方")
    assert tts_ready("y=kx+b") == "歪等于开艾克斯加必"


def test_split_sentences():
    assert split_sentences("你好！我们来做一道题。已知x=2，求x的平方？好的") == [
        "你好！", "我们来做一道题。", "已知x=2，求x的平方？", "好的",
    ]
    long = "，".join(["一二三四五六七八九十"] * 10)
    parts = split_sentences(long, max_len=30)
    assert all(len(p) <= 31 for p in parts) and "".join(parts).replace("，", "") == long.replace("，", "")


def test_empty():
    assert latex_to_speech("") == "" and tts_ready("") == "" and split_sentences("") == []
