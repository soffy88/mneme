"""
S0-3 验收：恶意 LLM 生成的表达式字符串必须被 AST 白名单拦截，不能被执行。

加固前，全仓库对 obase/sympy_runtime.py 的 _SafeVisitor（AST 白名单）零测试
覆盖——白名单代码本身写得像是有效的，但从未有测试真正验证过它会拦截典型的
沙箱逃逸手法。这条测试把常见的 Python 沙箱逃逸/代码执行手法逐一喂给
SymPyRuntime，断言全部被 SymPyRestrictedError 拦在 AST 校验阶段，不会真的
执行到底（比如真的读文件、真的起子进程）。同时用一条负向对照确认合法数学
表达式没被误杀——白名单不能严到把正常输入也拦掉。
"""

from __future__ import annotations

import pytest

from obase.sympy_runtime import SymPyRestrictedError, SymPyRuntime

MALICIOUS_EXPRESSIONS = [
    "__import__('os').system('id')",
    "__import__('os').popen('id').read()",
    "os.system('id')",
    "open('/etc/passwd').read()",
    "exec('import os; os.system(\"id\")')",
    'eval(\'__import__("os").system("id")\')',
    "compile('import os', '<x>', 'exec')",
    "().__class__.__bases__[0].__subclasses__()",
    "(1).__class__.__mro__[-1].__subclasses__()",
    "globals()",
    "locals()",
    "vars()",
    "getattr(__builtins__, 'exec')",
    "[c for c in ().__class__.__base__.__subclasses__()]",
    "import os",  # statement-level, caught in exec-mode pre-parse
]


@pytest.mark.parametrize("malicious_expr", MALICIOUS_EXPRESSIONS)
def test_malicious_expression_is_rejected_by_ast_whitelist(malicious_expr):
    rt = SymPyRuntime()
    with pytest.raises(SymPyRestrictedError):
        rt.evaluate(malicious_expr)


def test_bare_builtins_reference_is_harmless_not_real_builtins():
    """`__builtins__` 本身不在 forbidden_names 里（它只是一个 Name 引用，不是
    调用），会通过 AST 校验——但这不是漏洞：evaluate() 的 eval() 调用本身把
    globals 里的 __builtins__ 显式替换成空字典（``eval(code, {"__builtins__":
    {}}, ns)``），所以拿到的永远是无害的空字典，不是真的 builtins 模块。这是
    比 AST 白名单更底层的一道硬防线，这条测试把它显式钉住，防止未来有人"优化"
    掉这个空字典替换却没意识到那是安全边界的一部分。"""
    rt = SymPyRuntime()
    result = rt.evaluate("__builtins__")
    assert result.success
    assert result.value == {}


def test_malicious_expression_via_solve_conic_does_not_execute():
    """端到端：不孤立测沙箱工具本身，走真实求解主链路（solve_conic，S0 加固前
    完全绕过沙箱、直接对调用方字符串跑裸 sp.sympify() 的内核之一）确认恶意输入
    被拦截，优雅降级为 solvable=False，不是抛未捕获异常，更不是真的执行。"""
    from oprim.solve_conic import solve_conic

    result = solve_conic("__import__('os').system('id')")
    assert result.solvable is False


def test_malicious_expression_via_solve_derivative_does_not_execute():
    """同上，针对 solve_derivative（S0 加固前另一个绕过沙箱、裸 sp.sympify()
    的内核）。"""
    from oprim.solve_derivative import DerivativeSolveInput, solve_derivative

    result = solve_derivative(
        DerivativeSolveInput(expression="__import__('os').system('id')", variable="x")
    )
    assert result.solvable is False


def test_malicious_expression_via_solve_function_all_branches():
    """同上，覆盖 solve_function 里 S0 加固前裸 sp.sympify() 的四个任务分支
    （parity/compose/monotonicity/inverse）——不能只测一个分支就假设其它分支
    也安全，这正是这几个分支最初被漏掉的原因。"""
    from oprim.solve_function import FunctionSolveInput, solve_function

    malicious = "__import__('os').system('id')"
    for task, extra in [
        ("parity", {}),
        ("compose", {"g_expression": "x+1"}),
        ("monotonicity", {}),
        ("inverse", {}),
    ]:
        result = solve_function(
            FunctionSolveInput(expression=malicious, variable="x", task=task, **extra)
        )
        assert result.solvable is False, f"task={task} 未能拦截恶意输入"


def test_legitimate_expressions_are_not_falsely_rejected():
    """负向对照：白名单不能严到把正常数学表达式也拦掉——防止"为了安全过度
    收紧"这种反向的红线破坏（这次不是弱化红线，是防止误伤到教学场景本身
    要用的合法表达式）。"""
    rt = SymPyRuntime()
    legit_cases = [
        ("x**2 + 2*x + 1", {"x": 3}),
        ("sin(x) + cos(x)", {"x": 0}),
        ("sqrt(x)", {"x": 16}),
        ("factorial(n)", {"n": 5}),
    ]
    for expr, variables in legit_cases:
        result = rt.evaluate(expr, variables)
        assert result.success, f"合法表达式被误拦截：{expr} → {result.error}"
