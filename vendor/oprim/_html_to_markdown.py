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
