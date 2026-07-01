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

async def lsp_hover(
    path: str | Path,
    *,
    line: int,
    character: int,
    server: LspServerHandle,
) -> Hover | None:
    """单次获取光标位置的 hover 信息（类型/文档）。

    Args:
        path: 文件路径。
        line: 行号（0-based）。
        character: 列号（0-based）。
        server: LSP server handle。

    Returns:
        Hover（含 Markdown 格式文档），或 None（无 hover 信息）。

    Raises:
        LspOprimError: LSP 请求失败。

    Example:
        >>> h = await lsp_hover("src/main.py", line=10, character=5, server=server)
        >>> h.contents
        '```python\ndef foo() -> int\n```'
    """
    try:
        result = await server.request(
            "textDocument/hover",
            _text_doc_pos(path, line, character),
        )
    except Exception as e:
        raise LspOprimError(f"lsp_hover failed for '{path}':{line}", cause=e)

    if not result:
        return None

    contents = result.get("contents", "")
    if isinstance(contents, dict):
        contents = contents.get("value", "")
    elif isinstance(contents, list):
        contents = "\n".join(
            c.get("value", c) if isinstance(c, dict) else str(c)
            for c in contents
        )

    r = result.get("range", {})
    start = r.get("start", {}) if r else {}
    return Hover(
        contents=str(contents),
        range_start_line=start.get("line"),
        range_start_char=start.get("character"),
    )
