"""Extract main readable content from HTML, stripping boilerplate tags."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

_STRIP_TAGS = {"script", "style", "nav", "footer", "header", "aside"}
_CONTENT_TAGS = {"article", "main"}

_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_ENTITIES = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&apos;": "'",
    "&#39;": "'",
    "&nbsp;": " ",
}


def _decode_entities(text: str) -> str:
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    # numeric entities
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), text)
    return text


class _ContentExtractor(HTMLParser):
    """Two-pass HTML parser: strips noise tags, collects article/main if found."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._skip_depth: dict[str, int] = {t: 0 for t in _STRIP_TAGS}
        self._content_depth: dict[str, int] = {t: 0 for t in _CONTENT_TAGS}
        self._in_skip = 0          # total nesting depth of skip tags
        self._in_content = 0       # total nesting depth of content tags
        self.content_parts: list[str] = []
        self.full_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[Any]) -> None:
        tag = tag.lower()
        if tag in _STRIP_TAGS:
            self._in_skip += 1
        if tag in _CONTENT_TAGS:
            self._in_content += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _STRIP_TAGS and self._in_skip > 0:
            self._in_skip -= 1
        if tag in _CONTENT_TAGS and self._in_content > 0:
            self._in_content -= 1

    def handle_data(self, data: str) -> None:
        if self._in_skip:
            return
        text = _decode_entities(data)
        self.full_parts.append(text)
        if self._in_content:
            self.content_parts.append(text)

    def handle_entityref(self, name: str) -> None:
        entity = f"&{name};"
        text = _decode_entities(entity)
        if not self._in_skip:
            self.full_parts.append(text)
            if self._in_content:
                self.content_parts.append(text)

    def handle_charref(self, name: str) -> None:
        if name.startswith("x") or name.startswith("X"):
            char = chr(int(name[1:], 16))
        else:
            char = chr(int(name))
        if not self._in_skip:
            self.full_parts.append(char)
            if self._in_content:
                self.content_parts.append(char)


def _looks_like_html(text: str) -> bool:
    """Heuristic: contains at least one HTML tag."""
    return bool(_TAG_RE.search(text))


def _collapse_whitespace(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    # Remove consecutive blank lines
    result: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        result.append(line)
        prev_blank = is_blank
    return "\n".join(result).strip()


def extract_main_content(html: str) -> str:
    """Return the main readable text from *html*.

    Parameters
    ----------
    html:
        Raw HTML string.  Empty string → ``""``.  Non-HTML text → returned
        as-is.

    Returns
    -------
    str
        Plain text with boilerplate (script/style/nav/footer/header/aside)
        removed.  If an ``<article>`` or ``<main>`` element is found, only
        its text is returned.
    """
    if not html:
        return ""

    if not _looks_like_html(html):
        return html

    parser = _ContentExtractor()
    try:
        parser.feed(html)
    except Exception:
        # Fallback: strip tags with regex
        stripped = _TAG_RE.sub(" ", html)
        return _collapse_whitespace(_decode_entities(stripped))

    chosen = parser.content_parts if parser.content_parts else parser.full_parts
    return _collapse_whitespace("".join(chosen))
