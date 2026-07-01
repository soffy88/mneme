"""Auto-split from hicode whl."""

from __future__ import annotations
import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from ._exceptions import ParseOprimError

@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    lines: list[str]

@dataclass
class FileDiff:
    old_path: str
    new_path: str
    hunks: list[Hunk]

def redact_secrets(
    text: str,
    *,
    patterns: list[str] | None = None,
    replacement: str = "[REDACTED]",
) -> str:
    """从文本中脱敏 API key / 密码 / token 等敏感信息。

    Args:
        text: 待脱敏的文本。
        patterns: 自定义正则列表；None 使用内置默认规则。
        replacement: 替换字符串，默认 "[REDACTED]"。

    Returns:
        脱敏后的文本。

    Raises:
        ParseOprimError: 正则编译失败。

    Example:
        >>> redact_secrets("api_key=sk-abc123xyz789abc123xyz789abc123xyz")
        'api_key=[REDACTED]'
    """
    active = patterns if patterns is not None else _DEFAULT_PATTERNS
    result = text
    try:
        for pat in active:
            compiled = re.compile(pat)
            # 若有捕获组，替换 group(2)（值部分）；否则替换整个匹配
            def _repl(m: re.Match) -> str:  # type: ignore[type-arg]
                if m.lastindex and m.lastindex >= 2:
                    return m.group(0).replace(m.group(2), replacement)
                return replacement
            result = compiled.sub(_repl, result)
    except re.error as e:
        raise ParseOprimError(f"invalid pattern: {e}", cause=e)
    return result
