"""obase.sandbox_selfcheck —— S0 沙箱加固生产自检（W4 追加，事故后修复）。

背景：S0 的沙箱加固从 push（b1b433d）到真正在生产生效之间，存在一段"裸奔
窗口"——docker-compose 的 PYTHONPATH 一直不含 /app/vendor，生产容器实际
装配的是站点包（site-packages）里未加固的旧内核副本，不是本仓 vendor/ 的
加固版本。pytest 测试环境（pythonpath=["vendor","."]）一直是绿的，这恰恰
掩盖了生产环境根本没生效这件事——**没有任何东西在生产环境里验证过加固
真的生效**，这正是这个洞能存在这么久的根本原因。

这个模块把 S0-1"零绕过"结构断言 + "沙箱确实是加固版本、不是旧副本"的
能力/来源检查，包成一份单源定义——tests/test_sandbox_zero_bypass.py 和
本模块共用同一份 EXPECTED_KERNELS/NUMERIC_ONLY_KERNELS 定义，不各自维护
一份副本——同时提供 check_or_die()，供容器启动时调用一次（同
docker-compose.yml 里 "alembic upgrade head && uvicorn ..." 那条
"检查不过就不对外提供服务"的处置原则）。

S0-W5 架构调整（第 4 次同类洞后，2026-07）：原先"字符串求值内核必须调用
AST_VALIDATED_ENTRY_POINTS / 不得残留 sp.sympify("的检查（原
STRING_EVAL_KERNELS/AST_VALIDATED_ENTRY_POINTS/VISUALIZATION_KERNELS 三个
常量，已删除）是允许清单模式——只挑着测"已知在 solve_*/可视化清单里"的
文件，且用字符串匹配天然漏 parse_expr()/别名导入两类变体，这正是
verify_step/grade_question/compute_feedback/socratic_service/
paper_grading/math_grade 六处真实漏洞逃过前几轮检测的根本原因之一。现改用
obase.sandbox_ast_audit.scan_repo()：拒绝清单模式，AST 解析（含 import 别名
追踪），扫描全仓第一方代码而非"记得列在清单里"的文件——见
_check_repo_wide_ast_audit()。NUMERIC_ONLY_KERNELS 的 run_isolated 检查
保留：纯数值内核没有表达式字符串、没有危险符号调用可抓，AST 拒绝清单结构上
抓不到"该包 run_isolated 但没包"这类风险，只能继续用专属检查。
"""

from __future__ import annotations

import inspect
from pathlib import Path


class SandboxSelfCheckError(Exception):
    """沙箱自检失败——生产容器不应该在这种状态下对外提供服务。"""


EXPECTED_KERNELS = {
    "solve_conic.py",
    "solve_derivative.py",
    "solve_function.py",
    "solve_geometry3d.py",
    "solve_probability.py",
    "solve_sequence.py",
    "solve_trig.py",
}

# 纯数值 dataclass in/out，没有表达式字符串可做 AST 校验——真正风险是病态
# 数值量级导致的 DoS，走 run_isolated() 复用 fork+timeout+内存上限。
NUMERIC_ONLY_KERNELS = {
    "solve_geometry3d.py",
    "solve_probability.py",
    "solve_sequence.py",
}


def _oprim_source_dir() -> Path:
    """当前实际解析到的 oprim 包目录——不硬编码 vendor 路径，就用运行时
    真实 import 到的那份（这样如果 PYTHONPATH 又配错、oprim 解析回了
    站点包，本函数会如实指向站点包目录，_check_source_is_vendor 才能
    据此判断出"解析错了"）。
    """
    import oprim

    return Path(inspect.getfile(oprim)).resolve().parent


def _check_hardened_version_loaded() -> list[str]:
    """obase.sympy_runtime 确实是加固后的版本（有 run_isolated 方法），
    不是 S0 加固前的旧副本——防止"看起来装对了但其实是旧代码"的假阳性。
    """
    from obase.sympy_runtime import SymPyRuntime

    if hasattr(SymPyRuntime, "run_isolated"):
        return []
    return [
        "obase.sympy_runtime.SymPyRuntime 缺少 run_isolated 方法——"
        "当前装配的很可能是 S0 加固前的旧副本。"
    ]


def _check_resolves_to_vendor_not_site_packages() -> list[str]:
    """最直接的信号：这次事故的根因就是 oprim/oskill/omodul/obase 解析到了
    site-packages 而不是本仓 vendor/。"""
    from obase.sympy_runtime import SymPyRuntime

    resolved = Path(inspect.getfile(SymPyRuntime)).resolve()
    if "site-packages" in resolved.parts:
        return [
            f"obase.sympy_runtime 解析到站点包（{resolved}），不是 vendor/——"
            f"PYTHONPATH 没有把 vendor/ 排在前面，S0 加固对当前进程完全不生效。"
        ]
    return []


def _check_zero_bypass() -> list[str]:
    """S0-1：solve_* 内核清单没有漂移，且纯数值内核都走 run_isolated——同
    tests/test_sandbox_zero_bypass.py 的检查逻辑，单源。

    字符串求值内核"是否绕过沙箱"不再由本函数判断（原 STRING_EVAL_KERNELS/
    AST_VALIDATED_ENTRY_POINTS 逻辑已删除，见模块顶部说明）——那类风险现由
    _check_repo_wide_ast_audit() 覆盖，且覆盖面是全仓而不只是这 7 个文件。
    """
    errors: list[str] = []
    oprim_dir = _oprim_source_dir()

    found = {p.name for p in oprim_dir.glob("solve_*.py")}
    if found != EXPECTED_KERNELS:
        errors.append(
            f"solve_* 内核清单不是预期的 7 个（found={sorted(found)}），"
            f"本自检需要同步更新才能继续保护新内核。"
        )

    for name in sorted(NUMERIC_ONLY_KERNELS & found):
        source = (oprim_dir / name).read_text(encoding="utf-8")
        if "run_isolated" not in source:
            errors.append(f"{name} 没有调用 run_isolated（纯数值内核绕过沙箱）")

    return errors


def _check_repo_wide_ast_audit() -> list[str]:
    """S0-W5：AST 级全仓扫描——任何第一方代码裸调用 sympy.sympify/
    sympy.parsing.sympy_parser.parse_expr/eval/exec/compile/__import__（除
    obase.sympy_runtime 自身实现）都会被抓到，不依赖维护一份"哪些文件该
    测"的清单，也不依赖字符串匹配（会漏别名导入/parse_expr 等变体）。见
    obase.sandbox_ast_audit.scan_repo()。
    """
    from obase.sandbox_ast_audit import scan_repo

    return scan_repo()


def collect_findings() -> list[str]:
    """跑一遍全部自检项，返回问题描述列表（空列表 = 全部通过）。拆成独立
    函数（而不是直接在 check_or_die 里内联）是为了让测试能分别验证每一类
    检测逻辑本身是否work，不用每次都靠"当前环境状态正好触发"来测。
    """
    findings: list[str] = []
    findings += _check_hardened_version_loaded()
    findings += _check_resolves_to_vendor_not_site_packages()
    findings += _check_zero_bypass()
    findings += _check_repo_wide_ast_audit()
    return findings


def check_or_die() -> None:
    """容器启动时调用一次。任何一项不过直接抛 SandboxSelfCheckError，
    调用方（docker-compose 的启动命令）应该让容器因此启动失败，而不是
    带着未加固/装错版本的沙箱静默对外提供服务——同 alembic 迁移失败
    "不对外提供服务"的处置原则。
    """
    findings = collect_findings()
    if findings:
        raise SandboxSelfCheckError(
            "S0 沙箱加固自检失败，拒绝对外提供服务：\n- " + "\n- ".join(findings)
        )


if __name__ == "__main__":
    check_or_die()
    print("S0 沙箱加固自检通过：vendor/ 生效，全仓 AST 扫描零绕过。")
