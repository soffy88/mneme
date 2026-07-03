"""刻意练习细颗粒反馈（教育理念 07）：practice/submit 依赖 verify_steps_chain 确定性定位首错步。
守护端点所依赖的契约（first_wrong_step/step_verdicts）。verify_steps_chain 本体见 test_step_grading。"""

from oskill import verify_steps_chain


def test_locates_first_wrong_arithmetic_step():
    # 第 2 步算术不成立(2+3=6)，应被定位为首个错步(0-based=1)
    steps = ["1+1=2", "2+3=6", "6-1=5"]
    chain = verify_steps_chain(steps)
    assert "first_wrong_step" in chain
    assert "step_verdicts" in chain
    assert chain["first_wrong_step"] == 1


def test_all_correct_no_wrong_step():
    chain = verify_steps_chain(["1+1=2", "2+2=4"])
    assert chain["first_wrong_step"] is None


def test_empty_steps_safe():
    chain = verify_steps_chain([])
    assert chain["first_wrong_step"] is None
