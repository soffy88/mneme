"""obase.sandbox_selfcheck 自身的测试——不是测"7 内核有没有绕过"（那是
test_sandbox_zero_bypass.py 的职责，两者现在共用同一份常量单源），而是
测这个自检模块本身：它在正常环境下真的通过，并且在真实发生过的三种
故障场景下（vendor 未生效/装了旧副本/内核本身绕过）真的能拦下来——不是
只在“凑巧当前环境是好的”这一种情况下显得有用。

背景：S0 沙箱加固 push 后，生产容器的 PYTHONPATH 一直不含 /app/vendor，
没有任何东西在生产环境验证过加固真的生效，这个洞存在了很久都没被发现。
这个测试文件 + sandbox_selfcheck.check_or_die() 就是防止这类"改了代码、
没人在生产验证过"的坑再次悄悄发生的机制。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from obase.sandbox_selfcheck import (
    EXPECTED_KERNELS,
    SandboxSelfCheckError,
    check_or_die,
    collect_findings,
)


def test_passes_in_current_correctly_configured_environment():
    """正向对照：当前测试环境（pytest 的 vendor-first pythonpath）本身
    就应该是自检通过的状态——如果这条都不过，说明自检逻辑本身写错了，
    不是环境的问题。"""
    findings = collect_findings()
    assert findings == [], f"当前环境不应该有自检问题，但发现：{findings}"
    check_or_die()  # 不应该抛异常


def test_detects_kernel_resolving_to_site_packages():
    """复现真实事故本身：oprim/obase 解析到站点包而不是 vendor/ 时，
    必须被拦下来——这正是 PYTHONPATH 配错时的真实症状。"""
    from obase.sandbox_selfcheck import _check_resolves_to_vendor_not_site_packages

    fake_path = "/usr/local/lib/python3.12/site-packages/obase/sympy_runtime.py"
    with patch("inspect.getfile", return_value=fake_path):
        findings = _check_resolves_to_vendor_not_site_packages()
    assert findings != []
    assert "site-packages" in findings[0]


def test_detects_pre_hardening_version_missing_run_isolated():
    """复现"装了旧副本"场景：即使 vendor/ 在 sys.path 上，如果加载到的
    SymPyRuntime 是 S0 加固前的版本（没有 run_isolated 方法），也要拦下来
    ——防止"vendor 生效了，但版本是旧的"这种更隐蔽的假阳性。"""
    from obase.sandbox_selfcheck import _check_hardened_version_loaded

    class _PreHardeningSymPyRuntime:
        """模拟 S0 之前的版本——没有 run_isolated。"""

    with patch("obase.sympy_runtime.SymPyRuntime", _PreHardeningSymPyRuntime):
        findings = _check_hardened_version_loaded()
    assert findings != []
    assert "run_isolated" in findings[0]


def test_detects_numeric_kernel_bypassing_sandbox():
    """复现 solve_sequence 加固前的真实状态：纯数值内核 import 了
    SymPyRuntime 却完全没调用 run_isolated——用一个临时目录里的假内核
    文件复现，不依赖真实 vendor/oprim 当前是否已经修好。"""
    from obase.sandbox_selfcheck import _check_zero_bypass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        for name in EXPECTED_KERNELS:
            content = (
                "from obase.sympy_runtime import SymPyRuntime\n"
                "_runtime = SymPyRuntime()\n"
            )
            if name != "solve_sequence.py":
                content += (
                    "_runtime.run_isolated(lambda: 1)\n"
                    if name
                    in {
                        "solve_geometry3d.py",
                        "solve_probability.py",
                    }
                    else "_runtime.evaluate('x')\n"
                )
            (tmp_path / name).write_text(content, encoding="utf-8")

        with patch("obase.sandbox_selfcheck._oprim_source_dir", return_value=tmp_path):
            findings = _check_zero_bypass()

    assert any("solve_sequence.py" in f and "run_isolated" in f for f in findings)


def test_repo_wide_ast_audit_is_wired_into_collect_findings():
    """S0-W5：_check_zero_bypass() 不再检测"字符串求值内核是否绕过"（原
    STRING_EVAL_KERNELS/AST_VALIDATED_ENTRY_POINTS 逻辑已删除，见
    tests/test_sandbox_ast_audit.py 里对该风险的专属覆盖）——但
    collect_findings() 必须真的把 sandbox_ast_audit.scan_repo() 的结果
    折进去，不能"删了旧检查却忘了接新检查"，用 mock 验证接线本身，不依赖
    当前仓库状态是否干净。"""
    from obase.sandbox_selfcheck import collect_findings

    with patch(
        "obase.sandbox_ast_audit.scan_repo",
        return_value=["fake/path.py:1 裸调用 sympy.sympify()——未经沙箱"],
    ):
        findings = collect_findings()

    assert any("fake/path.py" in f for f in findings)


def test_missing_kernel_file_is_detected():
    """内核清单本身对不上（比如某个 solve_*.py 被误删/改名）也要拦下来，
    不能悄悄跳过检查。"""
    from obase.sandbox_selfcheck import _check_zero_bypass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        for name in sorted(EXPECTED_KERNELS)[:-1]:  # 故意少放一个
            (tmp_path / name).write_text(
                "from obase.sympy_runtime import SymPyRuntime\n"
                "_runtime = SymPyRuntime()\n"
                "_runtime.evaluate('x')\n",
                encoding="utf-8",
            )
        with patch("obase.sandbox_selfcheck._oprim_source_dir", return_value=tmp_path):
            findings = _check_zero_bypass()

    assert any("不是预期的 7 个" in f for f in findings)


def test_check_or_die_raises_with_all_findings_joined():
    with patch(
        "obase.sandbox_selfcheck.collect_findings",
        return_value=["问题一", "问题二"],
    ):
        with pytest.raises(SandboxSelfCheckError) as exc_info:
            check_or_die()
    assert "问题一" in str(exc_info.value)
    assert "问题二" in str(exc_info.value)
