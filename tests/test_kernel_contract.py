"""3O 内核契约守卫：内核仓静默回退（丢字段/入参）时 CI 立即失败。

这正是当初 omodul 被切回 main 没被发现的那类问题——pydantic 忽略多余 kwarg
不报错，功能静默失效。本测试断言 mneme 依赖的内核能力齐全。
"""
from services.kernel_selfcheck import check_kernel_contract


def test_kernel_contract_intact():
    missing = check_kernel_contract()
    assert missing == [], (
        "3O 内核契约缺失（内核仓可能不在 feat/edu-audit-fixes 分支）: " + ", ".join(missing)
    )
