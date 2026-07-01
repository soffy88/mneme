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

async def lsp_completion(
    path: str | Path,
    *,
    line: int,
    character: int,
    server: LspServerHandle,
    trigger_character: str | None = None,
) -> list[Completion]:
    """单次获取补全候选列表。

    Args:
        path: 文件路径。
        line: 行号（0-based）。
        character: 列号（0-based）。
        server: LSP server handle。
        trigger_character: 触发补全的字符（如 "." "("），None 为手动触发。

    Returns:
        Completion 列表（最多 50 个）。

    Raises:
        LspOprimError: LSP 请求失败。

    Example:
        >>> completions = await lsp_completion("src/main.py",
        ...     line=10, character=8, server=server)
        >>> completions[0].label
        'parse_args'
    """
    context: dict[str, Any] = {"triggerKind": 2 if trigger_character else 1}
    if trigger_character:
        context["triggerCharacter"] = trigger_character

    try:
        result = await server.request(
            "textDocument/completion",
            {**_text_doc_pos(path, line, character), "context": context},
        )
    except Exception as e:
        raise LspOprimError("lsp_completion failed", cause=e)

    items = []
    if isinstance(result, dict):
        items = result.get("items", [])
    elif isinstance(result, list):
        items = result

    completions = []
    for item in items[:50]:  # 限制最多50个
        doc = item.get("documentation", "")
        if isinstance(doc, dict):
            doc = doc.get("value", "")
        completions.append(Completion(
            label=item.get("label", ""),
            kind=item.get("kind"),
            detail=item.get("detail", ""),
            documentation=str(doc),
            insert_text=item.get("insertText", item.get("label", "")),
        ))
    return completions
