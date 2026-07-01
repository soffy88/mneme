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

async def lsp_code_action(
    path: str | Path,
    *,
    start_line: int,
    start_character: int,
    end_line: int,
    end_character: int,
    server: LspServerHandle,
    only_kinds: list[str] | None = None,
) -> list[CodeAction]:
    """单次获取指定范围的代码操作（quick fix / refactor 等）。

    Args:
        path: 文件路径。
        start_line: 范围起始行（0-based）。
        start_character: 范围起始列。
        end_line: 范围结束行。
        end_character: 范围结束列。
        server: LSP server handle。
        only_kinds: 过滤的 CodeAction kind 列表，None 表示全部返回。

    Returns:
        CodeAction 列表。

    Raises:
        LspOprimError: LSP 请求失败。

    Example:
        >>> actions = await lsp_code_action("src/main.py",
        ...     start_line=5, start_character=0,
        ...     end_line=5, end_character=10, server=server)
        >>> [a.title for a in actions]
        ['Import os', 'Add type annotation']
    """
    params: dict[str, Any] = {
        "textDocument": _text_doc(path),
        "range": {
            "start": _position(start_line, start_character),
            "end": _position(end_line, end_character),
        },
        "context": {"diagnostics": []},
    }
    if only_kinds:
        params["context"]["only"] = only_kinds

    try:
        result = await server.request("textDocument/codeAction", params)
    except Exception as e:
        raise LspOprimError("lsp_code_action failed", cause=e)

    actions = []
    for item in (result or []):
        if isinstance(item, dict):
            actions.append(CodeAction(
                title=item.get("title", ""),
                kind=item.get("kind", ""),
                edit=_parse_workspace_edit(item["edit"]) if "edit" in item else None,
                command=item.get("command"),
            ))
    return actions
