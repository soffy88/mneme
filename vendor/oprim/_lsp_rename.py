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

async def lsp_rename(
    path: str | Path,
    *,
    line: int,
    character: int,
    new_name: str,
    server: LspServerHandle,
) -> WorkspaceEdit:
    """单次重命名符号，返回需要应用的 WorkspaceEdit。

    Args:
        path: 文件路径。
        line: 行号（0-based）。
        character: 列号（0-based）。
        new_name: 新名称。
        server: LSP server handle。

    Returns:
        WorkspaceEdit（含所有需要修改的文件和位置）。

    Raises:
        LspOprimError: LSP 请求失败或不支持重命名。

    Example:
        >>> edit = await lsp_rename("src/main.py", line=5, character=4,
        ...     new_name="process", server=server)
        >>> len(edit.changes)   # 受影响文件数
        3
    """
    try:
        result = await server.request(
            "textDocument/rename",
            {**_text_doc_pos(path, line, character), "newName": new_name},
        )
    except Exception as e:
        raise LspOprimError("lsp_rename failed", cause=e)

    if not result:
        return WorkspaceEdit()

    return _parse_workspace_edit(result)
