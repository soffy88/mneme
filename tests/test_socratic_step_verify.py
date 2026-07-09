"""苏格拉底确定性中间步拦截（含变量代入校验，item 3）。纯函数，无 DB。"""

from services.socratic_service import _try_verify_step, _verify_assignments


def test_intercepts_wrong_variable_value():
    # x²=4 ⟹ x=3：3 代回不成立 → 拦截
    assert _try_verify_step("x² = 4, 所以 x = 3") is not None
    assert _verify_assignments("x^2 = 4, 所以 x = 3") is not None


def test_allows_valid_root():
    # x²=4 ⟹ x=2（或 -2）：成立 → 不拦
    assert _verify_assignments("x² = 4, 所以 x = 2") is None
    assert _verify_assignments("x^2 = 4, x = -2") is None


def test_allows_valid_scaling_step():
    # 2x=6 ⟹ x=3 是正确缩放，不应误伤
    assert _verify_assignments("2x = 6, 所以 x = 3") is None


def test_intercepts_wrong_linear_solution():
    # 2x=6 ⟹ x=2：错 → 拦截
    assert _verify_assignments("2x = 6, x = 2") is not None


def test_isolated_variable_step_not_intercepted():
    # 无前序方程的孤立 "x=3" 无法判定 → 不拦（宁可不拦，不误伤）
    assert _try_verify_step("所以 x = 3") is None


def test_pure_arithmetic_still_checked():
    # 纯算术错误仍被既有逻辑拦截
    assert _try_verify_step("2 + 3 = 6") is not None
    assert _try_verify_step("2 + 3 = 5") is None


def test_no_leak_in_intercept_message():
    # 拦截提示不得包含正确数值/答案
    msg = _verify_assignments("x² = 4, x = 3")
    assert msg is not None
    assert "2" not in msg and "-2" not in msg


# X.7 补测试：以下覆盖此前零覆盖的分支——赋值语句写成"数值=变量"倒序形式、
# 解析失败的容错分支、多变量前序方程跳过、非赋值形式中间方程跳过。


def test_reversed_assignment_order_still_intercepts_wrong_value():
    # "3 = x" 而不是 "x = 3"（数值在左边）：x²=16 时 x=3 不成立，仍应拦截
    assert _verify_assignments("x² = 16, 3 = x") is not None


def test_reversed_assignment_order_allows_correct_value():
    # 倒序但值正确（x=4 满足 x²=16）：不应误伤
    assert _verify_assignments("x² = 16, 4 = x") is None


def test_unparseable_prior_equation_does_not_crash():
    # 前一个方程语法错误（sympy 解析失败）→ 容错跳过，不崩溃、不误拦
    assert _verify_assignments("y)( = 4, x = 2") is None


def test_unparseable_current_equation_does_not_crash():
    # 当前候选赋值语句语法错误 → 容错跳过
    assert _verify_assignments("x = 2, y)( = 4") is None


def test_multivar_prior_equation_skipped():
    # 前序方程含多个变量（x+y=10）时，跟单变量赋值(x=3)对不上变量集合，应跳过校验
    assert _verify_assignments("x + y = 10, x = 3") is None


def test_non_assignment_middle_equation_skipped_as_candidate():
    # 中间方程 2x=8 不是"变量=数值"的裸赋值形式，不当作候选校验，
    # 但不影响后面 x=4 对最初 x²=16 的校验（4满足，不拦）
    assert _verify_assignments("x**2 = 16, 2*x = 8, x = 4") is None
