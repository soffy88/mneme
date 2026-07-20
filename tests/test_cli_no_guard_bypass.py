"""W5 Part C 红线：cli/mneme_cli.py 结构性不能绕过 guard/门控。

静态断言：CLI 不 import 任何 oprim/oskill/omodul/services.models/直连 DB 的
东西——只能通过 HTTP 打 /v1/auth/* 和 /mcp/*，跟人类用户走同一套护栏。对照
tests/test_memory_no_gating_coupling.py、
tests/test_partner_no_self_judged_mastery.py 同一红线测试模式。
"""

from __future__ import annotations

import ast
from pathlib import Path

_FORBIDDEN_IMPORT_PREFIXES = (
    "oprim",
    "oskill",
    "omodul",
    "services.models",
    "services.mcp_router",
    "sqlalchemy",
    "obase.db",
)

_CLI_MODULE = Path(__file__).parent.parent / "cli" / "mneme_cli.py"


def _imported_module_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_cli_never_imports_backend_internals():
    source = _CLI_MODULE.read_text(encoding="utf-8")
    imported = _imported_module_names(source)
    hits = [
        name
        for name in _FORBIDDEN_IMPORT_PREFIXES
        if any(imp == name or imp.startswith(name + ".") for imp in imported)
    ]
    assert not hits, (
        f"cli/mneme_cli.py 实际 import 了后端内部模块 {hits}——"
        "违反红线（CLI 只能经 HTTP /v1/auth/*、/mcp/* 操作，不能直连数据库/内核）"
    )


def test_cli_only_calls_v1_auth_and_mcp_paths():
    """CLI 里所有硬编码的 HTTP 路径必须落在 /v1/auth/* 或 /mcp/* 下。"""
    import re

    source = _CLI_MODULE.read_text(encoding="utf-8")
    paths = re.findall(r'"(/[a-zA-Z0-9_/{}\-]+)"', source)
    offenders = [
        p for p in paths if not (p.startswith("/v1/auth/") or p.startswith("/mcp/"))
    ]
    assert not offenders, f"CLI 出现非 /v1/auth/* 或 /mcp/* 的硬编码路径：{offenders}"
