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

async def lsp_format(
    path: str | Path,
    *,
    server: LspServerHandle,
    tab_size: int = 4,
    insert_spaces: bool = True,
) -> list[TextEdit]:
    """单次格式化整个文件，返回 TextEdit 列表。

    Args:
        path: 文件路径。
        server: LSP server handle。
        tab_size: Tab 大小，默认 4。
        insert_spaces: True 使用空格，False 使用 Tab。

    Returns:
        TextEdit 列表（空列表表示文件已格式化，无需修改）。

    Raises:
        LspOprimError: LSP 请求失败。

    Example:
        >>> edits = await lsp_format("src/main.py", server=server)
        >>> len(edits)
        3
    """
    try:
        result = await server.request(
            "textDocument/formatting",
            {
                "textDocument": _text_doc(path),
                "options": {
                    "tabSize": tab_size,
                    "insertSpaces": insert_spaces,
                },
            },
        )
    except Exception as e:
        raise LspOprimError(f"lsp_format failed for '{path}'", cause=e)

    return _parse_text_edits(result or [])
