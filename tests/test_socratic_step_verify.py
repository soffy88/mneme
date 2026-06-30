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
