"""obase.sandbox_ast_audit —— S0-W5：AST 级全仓沙箱扫描（结构性拒绝清单，
非字符串 grep）。

背景（第 4 次同类洞，这次坐在真实学生输入上）：此前的检测方式是字符串
grep（旧版 tests/test_sandbox_zero_bypass.py + obase/sandbox_selfcheck.py
只匹配字面量 ``"sp.sympify("`` / ``"sympy.sympify("``）——这种方式天然漏
变体：``parse_expr()``（同类风险，字符串形态完全不同）、别名导入
（``from sympy import sympify as X``）、多行调用等都不会被字符串匹配
抓到。W5 前置 sweep 就是这么漏掉了 verify_step.py/grade_question.py/
compute_feedback.py/socratic_service.py/paper_grading.py 五个真实处理
学生输入（聊天/判分/OCR手写）的裸解析点。

设计反转：从"允许清单（列出已知修好的内核）"变成"拒绝清单（除了沙箱自己
的实现文件，任何第一方代码都不能裸调这些危险符号）"——前者每次新增内核/
调用点都要有人记得手动更新才不漏，已经连续踩坑 4 轮；后者是结构性的：
新代码只要想走裸解析，自动被这条检查拦下来，不需要有人记得更新白名单。
用真 AST 解析（追踪 import 别名），不是字符串匹配。
"""

from __future__ import annotations

import ast
from pathlib import Path

# 危险符号：sympy 侧的字符串求值入口 + Python 原生代码执行入口。
DANGEROUS_DOTTED_NAMES = frozenset(
    {
        "sympy.sympify",
        "sympy.parsing.sympy_parser.parse_expr",
    }
)
DANGEROUS_BUILTINS = frozenset({"eval", "exec", "compile", "__import__"})

# 唯一豁免：沙箱自己的实现文件——这里的 eval/compile 调用就是这套机制
# 本身，前面必然有 _validate_ast() 校验，是被检查对象不是被检查目标。
SANDBOX_IMPLEMENTATION_FILE = "vendor/obase/sympy_runtime.py"

# 已人工审查过、确认无风险的极少数例外（不是"相信它已经修好"，是"打开
# 文件看过，参数是硬编码字面量，不是外部输入"）——刻意保持这份清单极短，
# 任何新增都需要真的打开文件确认过再加，不能因为"看起来像同一类内核"就加。
REVIEWED_SAFE_EXCEPTIONS = frozenset(
    {
        # __import__("json") 是懒加载写法，参数是硬编码字符串字面量，不是
        # 外部输入；okx_rest_call.py 是加密货币交易所辅助模块，跟数学/
        # 教学求值路径无关（W5 前置 sweep 确认）。
        ("vendor/oprim/okx_rest_call.py", 50),
    }
)

SCAN_DIRS = (
    "vendor",
    "packages/mneme-core/mneme_core",
    "packages/mneme-agent/mneme_agent",
    "services",
    "tasks",
    "scripts",
)

# 测试代码不算：测试里直接构造 sympy 对象做期望值断言，不是"外部输入到达
# 生产请求路径"，AST 扫描的目标是请求路径，不是测试夹具。
EXCLUDED_DIR_PARTS = frozenset(
    {"tests", "test", "__pycache__", ".venv", "node_modules"}
)


class _ImportTracker(ast.NodeVisitor):
    """追踪模块级 import，把危险符号的实际绑定名字解出来（处理别名）。"""

    def __init__(self) -> None:
        self.name_to_dotted: dict[str, str] = {}  # 裸名字 -> 危险点分名
        self.module_alias: dict[str, str] = {}  # {绑定名: 真实模块名}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            bound = alias.asname or alias.name
            self.module_alias[bound] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            for alias in node.names:
                bound = alias.asname or alias.name
                full = f"{node.module}.{alias.name}"
                if full in DANGEROUS_DOTTED_NAMES:
                    self.name_to_dotted[bound] = full
        self.generic_visit(node)


def _attr_chain(node: ast.AST) -> str | None:
    """把 a.b.c 形式的 AST 还原成 "a.b.c" 字符串；非属性链返回 None。"""
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def _resolve_call_target(func: ast.AST, tracker: _ImportTracker) -> str | None:
    """把一次调用的 func 表达式解析成危险点分名（命中则返回，否则 None）。
    处理三种形态：裸名字调用（内置函数/from-import 别名）、属性调用（经
    模块 import 别名）。"""
    if isinstance(func, ast.Name):
        if func.id in DANGEROUS_BUILTINS:
            return func.id
        return tracker.name_to_dotted.get(func.id)

    chain = _attr_chain(func)
    if chain is None:
        return None
    # chain 形如 "sp.sympify" 或 "sympy.parsing.sympy_parser.parse_expr"
    # —— 把开头的模块别名替换回真实模块名再比对。
    head, _, rest = chain.partition(".")
    real_head = tracker.module_alias.get(head, head)
    full = f"{real_head}.{rest}" if rest else real_head
    return full if full in DANGEROUS_DOTTED_NAMES else None


def _scan_file(path: Path, repo_root: Path) -> list[str]:
    rel = str(path.relative_to(repo_root)).replace("\\", "/")
    if rel == SANDBOX_IMPLEMENTATION_FILE:
        return []

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return [f"{rel}: 无法解析（{exc}），需要人工确认是否存在风险"]

    tracker = _ImportTracker()
    tracker.visit(tree)

    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = _resolve_call_target(node.func, tracker)
        if target is None:
            continue
        if (rel, node.lineno) in REVIEWED_SAFE_EXCEPTIONS:
            continue
        findings.append(f"{rel}:{node.lineno} 裸调用 {target}()——未经沙箱")
    return findings


def scan_repo(repo_root: Path | None = None) -> list[str]:
    """扫描全仓第一方代码，返回发现列表（空列表 = 未发现裸调用危险符号）。"""
    root = repo_root or Path(__file__).resolve().parent.parent.parent
    findings: list[str] = []
    for scan_dir in SCAN_DIRS:
        base = root / scan_dir
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if any(part in EXCLUDED_DIR_PARTS for part in path.parts):
                continue
            findings.extend(_scan_file(path, root))
    return findings


if __name__ == "__main__":
    results = scan_repo()
    if results:
        print(f"发现 {len(results)} 处裸调用危险符号：")
        for f in results:
            print(f"- {f}")
    else:
        print("AST 全仓扫描通过：零裸调用危险符号。")
