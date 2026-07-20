"""obase.sandbox_ast_audit 自身的测试。

核心诉求（S0-W5，第 4 次同类洞后）：证明这个 AST 扫描器真的抓到了字符串
grep 结构性抓不到的两类变体——``parse_expr()``（字面量形态跟
``sp.sympify(`` 完全不同）、import 别名（``from sympy import sympify as
X`` 之后调用 ``X(...)``）。旧版 tests/test_sandbox_zero_bypass.py 的检查
只匹配字面量 "sp.sympify(" / "sympy.sympify("，这两类都会被完全漏过——
这正是 verify_step/grade_question/compute_feedback/socratic_service/
paper_grading/math_grade 六处真实漏洞逃过前几轮检测的根本原因。

每个测试用临时目录搭一个符合 SCAN_DIRS 布局的假仓库（如
``<tmp>/vendor/oprim/xxx.py``），而不是依赖真实仓库当前状态——这样测试
验证的是"扫描器的检测逻辑本身对不对"，不是"当前仓库碰巧是干净的"。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from obase.sandbox_ast_audit import scan_repo


def _write_fake_repo(files: dict[str, str]) -> Path:
    """在临时目录里按 {相对路径: 源码} 建一棵假仓库树，返回仓库根路径。"""
    tmp_path = Path(tempfile.mkdtemp())
    for rel_path, content in files.items():
        full = tmp_path / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    return tmp_path


def test_detects_raw_sp_sympify():
    root = _write_fake_repo(
        {
            "vendor/oprim/fake_kernel.py": (
                "import sympy as sp\n"
                "def f(expr_str):\n"
                "    return sp.sympify(expr_str)\n"
            )
        }
    )
    findings = scan_repo(root)
    assert any("fake_kernel.py" in f and "sympy.sympify" in f for f in findings)


def test_detects_parse_expr_that_string_grep_would_miss():
    """字符串 grep 只匹配 "sympify("，对 parse_expr() 完全看不见——这是
    W5 前置 sweep 漏掉 math_grade.py 的真实原因，AST 扫描器必须能抓到。"""
    root = _write_fake_repo(
        {
            "services/fake_grade.py": (
                "from sympy.parsing.sympy_parser import parse_expr\n"
                "def f(raw):\n"
                "    return parse_expr(raw)\n"
            )
        }
    )
    findings = scan_repo(root)
    assert any("fake_grade.py" in f and "parse_expr" in f for f in findings)


def test_detects_import_alias_that_string_grep_would_miss():
    """字符串 grep 匹配不到别名调用（"X(" 里的 X 跟 "sympify" 字面量无关）
    ——AST 扫描器追踪 import 别名解析真实调用目标，必须能抓到。"""
    root = _write_fake_repo(
        {
            "vendor/oprim/fake_alias.py": (
                "from sympy import sympify as _dangerous_alias\n"
                "def f(expr_str):\n"
                "    return _dangerous_alias(expr_str)\n"
            )
        }
    )
    findings = scan_repo(root)
    assert any("fake_alias.py" in f and "sympy.sympify" in f for f in findings)


def test_detects_module_aliased_attribute_call():
    """import sympy as 任意别名（不只是约定俗成的 "sp"）后调用
    别名.sympify()，也要能正确解析回真实模块名。"""
    root = _write_fake_repo(
        {
            "vendor/oprim/fake_module_alias.py": (
                "import sympy as totally_different_name\n"
                "def f(expr_str):\n"
                "    return totally_different_name.sympify(expr_str)\n"
            )
        }
    )
    findings = scan_repo(root)
    assert any("fake_module_alias.py" in f and "sympy.sympify" in f for f in findings)


def test_detects_dangerous_builtins():
    root = _write_fake_repo(
        {
            "vendor/oprim/fake_eval.py": "def f(s):\n    return eval(s)\n",
            "vendor/oprim/fake_exec.py": "def f(s):\n    exec(s)\n",
        }
    )
    findings = scan_repo(root)
    assert any("fake_eval.py" in f and "eval" in f for f in findings)
    assert any("fake_exec.py" in f and "exec" in f for f in findings)


def test_does_not_flag_safe_sandbox_usage():
    """走 SymPyRuntime 的 AST 校验入口（评审通过的安全模式）不应被误报。"""
    root = _write_fake_repo(
        {
            "vendor/oprim/fake_safe_kernel.py": (
                "from obase.sympy_runtime import SymPyRuntime\n"
                "_runtime = SymPyRuntime()\n"
                "def f(expr_str):\n"
                "    return _runtime.evaluate_auto(expr_str)\n"
            )
        }
    )
    findings = scan_repo(root)
    assert findings == []


def test_does_not_flag_unrelated_sympy_calls():
    """sympy 的其他函数（不在危险集合里）不应被误报——扫描器只针对具体点
    分名单，不是"提到 sympy 就报警"。"""
    root = _write_fake_repo(
        {
            "vendor/oprim/fake_unrelated.py": (
                "import sympy as sp\ndef f(x):\n    return sp.simplify(x)\n"
            )
        }
    )
    findings = scan_repo(root)
    assert findings == []


def test_exempts_sandbox_implementation_file_itself():
    """obase/sympy_runtime.py 自己内部的 eval/compile 调用是这套沙箱机制
    本身（前面必然有 _validate_ast 校验），不是被检查目标——必须豁免，
    否则加固实现自己都过不了自检。"""
    root = _write_fake_repo(
        {
            "vendor/obase/sympy_runtime.py": (
                "def evaluate(expr_str):\n    return eval(expr_str)\n"
            )
        }
    )
    findings = scan_repo(root)
    assert findings == []


def test_reviewed_safe_exception_is_honored():
    """REVIEWED_SAFE_EXCEPTIONS 里人工审查过的具体文件+行号必须被豁免——
    用真实登记的例外（vendor/oprim/okx_rest_call.py:50）验证豁免逻辑本身
    生效，不只是"代码里写了这个常量"。"""
    # 精确构造成第 50 行调用，匹配 REVIEWED_SAFE_EXCEPTIONS 里登记的行号。
    lines = ["# padding"] * 49 + ['__import__("json")']
    root = _write_fake_repo({"vendor/oprim/okx_rest_call.py": "\n".join(lines) + "\n"})
    findings = scan_repo(root)
    assert findings == []


def test_test_directories_are_excluded():
    """测试代码里直接构造 sympy 对象做期望值断言，不是"外部输入到达生产
    请求路径"，不应被扫描/误报。"""
    root = _write_fake_repo(
        {
            "vendor/tests/test_something.py": (
                "import sympy as sp\ndef f(x):\n    return sp.sympify(x)\n"
            )
        }
    )
    findings = scan_repo(root)
    assert findings == []


def test_current_repo_is_clean():
    """端到端回归：真实仓库当前状态必须是零绕过——直接证明这轮 6 处真实
    漏洞（verify_step/grade_question/compute_feedback×2/socratic_service/
    paper_grading/math_grade）确实都已经改用沙箱化入口，不再残留裸调用。"""
    findings = scan_repo()
    assert findings == [], f"全仓 AST 扫描不应有发现，但发现：{findings}"
