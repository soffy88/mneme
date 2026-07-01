"""
oprim: 文本解析与计算原子操作集
================================
包含：parse_unified_diff / compute_diff / detect_language
      html_to_markdown / redact_secrets / count_tokens / estimate_cost

归属约束
--------
✅ 全部为纯计算（无 IO / 无 subprocess）
✅ 失败抛 ParseOprimError
✅ 不互相裸调
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

from ._exceptions import ParseOprimError


# ---------------------------------------------------------------------------
# parse_unified_diff
# ---------------------------------------------------------------------------

@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    header: str
    lines: list[str]  # 保留 +/-/空格 前缀


@dataclass
class FileDiff:
    old_path: str
    new_path: str
    hunks: list[Hunk]


def parse_unified_diff(diff_text: str) -> list[FileDiff]:
    """解析 unified diff 文本为结构化表示。

    Args:
        diff_text: unified diff 字符串（git diff / diff -u 输出）。

    Returns:
        FileDiff 列表，每项含 old_path / new_path / hunks。

    Raises:
        ParseOprimError: diff 格式严重错误。

    Example:
        >>> diffs = parse_unified_diff(git_diff_output)
        >>> diffs[0].hunks[0].old_start
        10
    """
    if not diff_text.strip():
        return []

    file_diffs: list[FileDiff] = []
    current_file: FileDiff | None = None
    current_hunk: Hunk | None = None

    hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)")

    for line in diff_text.splitlines(keepends=True):
        stripped = line.rstrip("\n")

        if stripped.startswith("--- "):
            if current_hunk and current_file:
                current_file.hunks.append(current_hunk)
                current_hunk = None
            old_path = stripped[4:].split("\t")[0]
            old_path = old_path[2:] if old_path.startswith("a/") else old_path
            current_file = FileDiff(old_path=old_path, new_path="", hunks=[])

        elif stripped.startswith("+++ ") and current_file:
            new_path = stripped[4:].split("\t")[0]
            new_path = new_path[2:] if new_path.startswith("b/") else new_path
            current_file.new_path = new_path
            file_diffs.append(current_file)

        elif m := hunk_re.match(stripped):
            if current_hunk and current_file:
                current_file.hunks.append(current_hunk)
            current_hunk = Hunk(
                old_start=int(m.group(1)),
                old_count=int(m.group(2) or 1),
                new_start=int(m.group(3)),
                new_count=int(m.group(4) or 1),
                header=m.group(5).strip(),
                lines=[],
            )

        elif current_hunk is not None and stripped.startswith(("+", "-", " ")):
            current_hunk.lines.append(stripped)

    # 收尾
    if current_hunk and current_file:
        current_file.hunks.append(current_hunk)

    return file_diffs


# ---------------------------------------------------------------------------
# compute_diff
# ---------------------------------------------------------------------------

def compute_diff(
    old: str,
    new: str,
    *,
    path: str = "",
    context_lines: int = 3,
) -> str:
    """计算两个字符串之间的 unified diff。

    Args:
        old: 原始内容。
        new: 新内容。
        path: 显示在 diff header 里的文件路径（可选）。
        context_lines: 上下文行数，默认 3。

    Returns:
        unified diff 字符串；若内容相同返回空字符串。

    Raises:
        ParseOprimError: 生成 diff 失败（极少见）。

    Example:
        >>> compute_diff("a\nb\n", "a\nc\n", path="file.py")
        '--- a/file.py\n+++ b/file.py\n@@ -1,2 +1,2 @@\n a\n-b\n+c\n'
    """
    try:
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        label_a = f"a/{path}" if path else "original"
        label_b = f"b/{path}" if path else "modified"
        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=label_a, tofile=label_b,
            n=context_lines,
        )
        return "".join(diff)
    except Exception as e:  # pragma: no cover
        raise ParseOprimError("failed to compute diff", cause=e)


# ---------------------------------------------------------------------------
# detect_language
# ---------------------------------------------------------------------------

_EXT_MAP: dict[str, str] = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".sh": "bash", ".bash": "bash",
    ".zsh": "zsh",
    ".fish": "fish",
    ".sql": "sql",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "scss", ".sass": "sass",
    ".json": "json",
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".md": "markdown", ".mdx": "markdown",
    ".rst": "rst",
    ".tex": "latex",
    ".r": "r", ".R": "r",
    ".lua": "lua",
    ".vim": "vim",
    ".dockerfile": "dockerfile",
}

_FILENAME_MAP: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Makefile": "makefile",
    "makefile": "makefile",
    "GNUmakefile": "makefile",
    ".gitignore": "gitignore",
    ".env": "dotenv",
    "Cargo.toml": "toml",
    "pyproject.toml": "toml",
}


def detect_language(
    path: str | Path,
    *,
    content: str | None = None,
) -> str:
    """根据文件路径（和可选内容）检测编程语言。

    Args:
        path: 文件路径（使用扩展名和文件名判断）。
        content: 文件内容（可选，用于 shebang 检测）。

    Returns:
        小写语言标识字符串，如 "python" / "typescript" / "unknown"。

    Raises:
        ParseOprimError: 路径解析失败。

    Example:
        >>> detect_language("src/main.py")
        'python'
        >>> detect_language("Dockerfile")
        'dockerfile'
    """
    try:
        p = Path(path)
    except Exception as e:  # pragma: no cover
        raise ParseOprimError(f"invalid path: {path}", cause=e)

    # 精确文件名匹配
    if p.name in _FILENAME_MAP:
        return _FILENAME_MAP[p.name]

    # 扩展名匹配
    ext = p.suffix.lower()
    if ext in _EXT_MAP:
        return _EXT_MAP[ext]

    # shebang 检测
    if content:
        first_line = content.splitlines()[0] if content.strip() else ""
        if first_line.startswith("#!"):
            if "python" in first_line:
                return "python"
            if "node" in first_line or "deno" in first_line:
                return "javascript"
            if "bash" in first_line:
                return "bash"
            if "sh" in first_line:
                return "shell"

    return "unknown"


# ---------------------------------------------------------------------------
# html_to_markdown
# ---------------------------------------------------------------------------

def html_to_markdown(html: str) -> str:
    """将 HTML 字符串转换为 Markdown 格式（纯计算）。

    简化实现：处理常见标签（h1-h6 / p / pre / code / a / ul/ol/li / strong / em）。
    生产版可替换为 html2text 或 markdownify 库。

    Args:
        html: HTML 字符串。

    Returns:
        Markdown 字符串。

    Raises:
        ParseOprimError: HTML 解析失败。

    Example:
        >>> html_to_markdown("<h1>Hello</h1><p>World</p>")
        '# Hello\n\nWorld\n'
    """
    try:
        text = html

        # 移除 script / style 块
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)

        # 标题
        for i in range(6, 0, -1):
            text = re.sub(
                rf"<h{i}[^>]*>(.*?)</h{i}>",
                lambda m, n=i: f"\n{'#' * n} {m.group(1).strip()}\n",
                text, flags=re.DOTALL | re.IGNORECASE,
            )

        # 代码块
        text = re.sub(
            r"<pre[^>]*><code[^>]*>(.*?)</code></pre>",
            lambda m: f"\n```\n{m.group(1)}\n```\n",
            text, flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(r"<code[^>]*>(.*?)</code>", r"`\1`", text, flags=re.DOTALL | re.IGNORECASE)

        # 链接
        text = re.sub(r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', r"[\2](\1)", text, flags=re.DOTALL | re.IGNORECASE)

        # 粗体/斜体
        text = re.sub(r"<strong[^>]*>(.*?)</strong>", r"**\1**", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<b[^>]*>(.*?)</b>", r"**\1**", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<em[^>]*>(.*?)</em>", r"*\1*", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<i[^>]*>(.*?)</i>", r"*\1*", text, flags=re.DOTALL | re.IGNORECASE)

        # 列表项
        text = re.sub(r"<li[^>]*>(.*?)</li>", r"\n- \1", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[ou]l[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</[ou]l>", "\n", text, flags=re.IGNORECASE)

        # 段落 / 换行
        text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<hr\s*/?>", "\n---\n", text, flags=re.IGNORECASE)

        # 移除剩余标签
        text = re.sub(r"<[^>]+>", "", text)

        # HTML 实体
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")

        # 清理多余空行
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"

    except Exception as e:  # pragma: no cover
        raise ParseOprimError("html_to_markdown failed", cause=e)


# ---------------------------------------------------------------------------
# redact_secrets
# ---------------------------------------------------------------------------

_DEFAULT_PATTERNS: list[str] = [
    r"(?i)(api[_-]?key|apikey|api[_-]?secret)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{16,})['\"]?",
    r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?(\S{6,})['\"]?",
    r"(?i)(token|auth[_-]?token|access[_-]?token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{16,})['\"]?",
    r"(?i)(secret[_-]?key|secret)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{16,})['\"]?",
    r"sk-[A-Za-z0-9]{32,}",           # OpenAI style
    r"ghp_[A-Za-z0-9]{36}",           # GitHub PAT
    r"Bearer\s+[A-Za-z0-9_\-\.]{20,}",
]


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


# ---------------------------------------------------------------------------
# count_tokens
# ---------------------------------------------------------------------------

def count_tokens(
    messages: list[dict] | str,
    *,
    model: str = "claude-sonnet-4-6",
) -> int:
    """估算消息列表或字符串的 token 数量（纯计算）。

    使用 chars/4 近似估算（~4 chars per token）。生产版按模型家族
    替换为精确 tokenizer（tiktoken / Anthropic tokenizer）。

    Args:
        messages: 消息列表（list[dict]）或纯字符串。
        model: 目标模型名（影响 tokenizer 选择；当前均用近似值）。

    Returns:
        估算的 token 数量（int）。

    Raises:
        ParseOprimError: messages 格式无法序列化。

    Example:
        >>> count_tokens([{"role": "user", "content": "hello"}])
        4
        >>> count_tokens("hello world")
        3
    """
    try:
        if isinstance(messages, str):
            text = messages
        else:
            import json
            text = json.dumps(messages, ensure_ascii=False)
        # ~4 chars/token 近似；Claude 实际约 3.5-4.5
        return max(1, len(text) // 4)
    except Exception as e:  # pragma: no cover
        raise ParseOprimError("count_tokens failed", cause=e)


# ---------------------------------------------------------------------------
# estimate_cost
# ---------------------------------------------------------------------------

# 默认价格表（USD per token）：claude-sonnet-4-6
_DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"in": 3e-6, "out": 15e-6},
    "claude-opus-4-6": {"in": 15e-6, "out": 75e-6},
    "claude-haiku-4-5": {"in": 0.8e-6, "out": 4e-6},
}
_FALLBACK_PRICING = {"in": 3e-6, "out": 15e-6}


def estimate_cost(
    in_tokens: int,
    out_tokens: int,
    *,
    model: str = "claude-sonnet-4-6",
    pricing: dict[str, float] | None = None,
) -> float:
    """估算 LLM 调用成本（USD，纯计算）。

    Args:
        in_tokens: 输入 token 数。
        out_tokens: 输出 token 数。
        model: 模型名，用于查内置价格表。
        pricing: 自定义价格 dict，格式 {"in": float, "out": float}（USD/token）；
            提供时忽略 model 价格表。

    Returns:
        估算成本（USD，float）。

    Raises:
        ParseOprimError: pricing 格式错误。

    Example:
        >>> estimate_cost(1000, 500, model="claude-sonnet-4-6")
        0.0105
    """
    try:
        if pricing is not None:
            p = pricing
        else:
            p = _DEFAULT_PRICING.get(model, _FALLBACK_PRICING)
        return in_tokens * p["in"] + out_tokens * p["out"]
    except (KeyError, TypeError) as e:  # pragma: no cover
        raise ParseOprimError("invalid pricing format", cause=e)
