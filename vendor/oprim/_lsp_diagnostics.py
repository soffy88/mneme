"""Auto-split from hicode whl."""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from ._exceptions import OprimError
from ._protocols import LspServerHandle

class LspOprimError(OprimError):
    """LSP 请求失败。"""

@dataclass
class Diagnostic:
    path: str
    line: int
    character: int
    end_line: int
    end_character: int
    severity: int
    message: str
    source: str
    code: str | int | None = None

    @property
    def severity_name(self) -> str:
        return {1: 'error', 2: 'warning', 3: 'info', 4: 'hint'}.get(self.severity, 'unknown')

@dataclass
class Hover:
    contents: str
    range_start_line: int | None = None
    range_start_char: int | None = None

@dataclass
class Location:
    path: str
    start_line: int
    start_character: int
    end_line: int
    end_character: int

@dataclass
class Symbol:
    name: str
    kind: int
    path: str
    start_line: int
    start_character: int
    end_line: int
    end_character: int
    container: str = ''

    @property
    def kind_name(self) -> str:
        _kinds = {1: 'File', 2: 'Module', 3: 'Namespace', 4: 'Package', 5: 'Class', 6: 'Method', 7: 'Property', 8: 'Field', 9: 'Constructor', 10: 'Enum', 11: 'Interface', 12: 'Function', 13: 'Variable', 14: 'Constant', 15: 'String', 16: 'Number'}
        return _kinds.get(self.kind, f'Kind({self.kind})')

@dataclass
class Completion:
    label: str
    kind: int | None = None
    detail: str = ''
    documentation: str = ''
    insert_text: str = ''

@dataclass
class TextEdit:
    start_line: int
    start_character: int
    end_line: int
    end_character: int
    new_text: str

@dataclass
class WorkspaceEdit:
    changes: dict[str, list[TextEdit]] = field(default_factory=dict)

@dataclass
class CodeAction:
    title: str
    kind: str
    diagnostics: list[Diagnostic] = field(default_factory=list)
    edit: WorkspaceEdit | None = None
    command: dict | None = None

async def lsp_diagnostics(
    path: str | Path,
    *,
    server: LspServerHandle,
) -> list[Diagnostic]:
    """单次获取文件的诊断信息（错误/警告）。

    Args:
        path: 文件路径。
        server: LSP server handle（由 obase.lsp 注入）。

    Returns:
        Diagnostic 列表，按行号排序。

    Raises:
        LspOprimError: LSP 请求失败。

    Example:
        >>> diags = await lsp_diagnostics("src/main.py", server=server)
        >>> [d.message for d in diags if d.severity == 1]
        ['undefined name foo']
    """
    try:
        result = await server.request(
            "textDocument/diagnostic",
            {"textDocument": _text_doc(path)},
        )
    except Exception as e:
        raise LspOprimError(f"lsp_diagnostics failed for '{path}'", cause=e)

    items = result.get("items", []) if isinstance(result, dict) else (result or [])
    diags = []
    for d in items:
        r = d.get("range", {})
        start = r.get("start", {})
        end = r.get("end", {})
        diags.append(Diagnostic(
            path=str(Path(path).resolve()),
            line=start.get("line", 0),
            character=start.get("character", 0),
            end_line=end.get("line", 0),
            end_character=end.get("character", 0),
            severity=d.get("severity", 1),
            message=d.get("message", ""),
            source=d.get("source", ""),
            code=d.get("code"),
        ))
    return sorted(diags, key=lambda d: (d.line, d.character))
