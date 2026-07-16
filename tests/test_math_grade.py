"""②-3b-i 数学确定性符号判分 grade_math。"""

from services.math_grade import grade_math


def test_fraction_equals_decimal():
    assert grade_math("0.5", "1/2") is True


def test_multi_root_order_independent():
    assert grade_math("x=2 或 x=3", "x=3, x=2") is True
    assert grade_math("2,3", "3,2") is True


def test_implicit_multiplication_and_commutativity():
    assert grade_math("2x+1", "1+2*x") is True


def test_superscript_and_operators():
    assert grade_math("x^2", "x*x") is True


def test_wrong_answer():
    assert grade_math("x=2", "x=3") is False
    assert grade_math("1/3", "0.333") is False


def test_root_count_mismatch():
    assert grade_math("2", "2,3") is False


def test_non_math_falls_back_to_string_equality():
    assert grade_math("北京", "北京") is True
    assert grade_math(" 北京 ", "北京") is True  # 归一化
    assert grade_math("北京", "上海") is False
