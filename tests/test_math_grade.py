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


# —— 判分核查后补：真实题库 expected 大量带 LaTeX/$/尾标点，正确答案不应判错 ——
def test_latex_dollar_and_frac():
    assert grade_math("1/8, -3", "$\\frac{1}{8},-3$") is True
    assert grade_math("1/5", "frac{1}{5}$") is True  # 缺反斜杠也认


def test_latex_dollar_inequality_via_fallback():
    assert grade_math("a<0", "$a<0$") is True  # 关系式：符号相减失败→字符串回落


def test_trailing_punctuation_stripped():
    assert grade_math("7", "7 .") is True
    assert grade_math("5.5", "5.5 .") is True


def test_pi_and_sqrt():
    assert grade_math("2*pi", "$2 \\pi$") is True
    assert grade_math("sqrt(2)", "$\\sqrt{2}$") is True


def test_latex_wrong_still_wrong():
    assert grade_math("8*pi", "$52 \\pi$") is False  # 值不同仍判错，不放水


def test_latex_superscript_braces():
    assert grade_math("e^6-1", "$e^{6}-1$") is True


def test_latex_mathrm_and_whitespace():
    assert grade_math("p>m>n", "$\\mathrm{p}>\\mathrm{m}>\\mathrm{n}$") is True
    assert grade_math("a>=-1", "$a \\geq -1$") is True


# —— S1 真题库抽样核查后补（119 抽样、86.6%→需 ≥90%）——
def test_set_structural_equality():
    # sympy 对 FiniteSet 相减不报错也永不为 0，需先试结构相等 `==`（不能只靠 simplify(x-e)）
    assert grade_math("{3}", "$\\{3\\}$") is True
    assert grade_math("{1,2}", "$\\{2,1\\}$") is True  # 集合顺序无关


def test_infty_unicode_and_latex_normalise():
    assert grade_math("(0,+∞)", "$(0,+\\infty)$") is True
    assert grade_math("[1,+∞)", "$[1,+\\infty)$") is True


def test_chinese_enumeration_comma_as_separator():
    assert grade_math("1, [-1,1]", "$1 、[-1,1]$.") is True
