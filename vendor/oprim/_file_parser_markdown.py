"""Parse a Markdown file with optional YAML frontmatter."""

from __future__ import annotations

from pathlib import Path

import frontmatter

from oprim._document_types import ParsedMarkdown, Section
from oprim._exceptions import OprimError


def file_parser_markdown(*, file_path: Path) -> ParsedMarkdown:
    """Parse a Markdown file with optional YAML frontmatter.

    Args:
        file_path: Path to the Markdown file

    Returns:
        ParsedMarkdown with frontmatter, sections, body, title

    Raises:
        OprimError: File not found or parse error
    """
    if not file_path.exists():
        raise OprimError(f"file_not_found: {file_path}")

    try:
        post = frontmatter.load(str(file_path))
    except Exception as e:
        raise OprimError(f"markdown_parse_failed: {e}") from e

    body = post.content
    fm = dict(post.metadata)
    raw_title = fm.get("title")
    title: str | None = str(raw_title) if raw_title is not None else _extract_h1(body)
    sections = _extract_sections(body)

    return ParsedMarkdown(
        source_path=str(file_path),
        frontmatter=fm,
        sections=sections,
        body=body,
        title=title,
    )


def _extract_h1(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _extract_sections(body: str) -> list[Section]:
    sections: list[Section] = []
    current_title = ""
    current_level = 0
    current_lines: list[str] = []

    for line in body.splitlines():
        if line.startswith("#"):
            if current_title:
                sections.append(
                    Section(
                        title=current_title,
                        level=current_level,
                        content="\n".join(current_lines).strip(),
                    )
                )
            # Count leading #
            level = len(line) - len(line.lstrip("#"))
            current_title = line.lstrip("#").strip()
            current_level = level
            current_lines = []
        else:
            current_lines.append(line)

    if current_title:
        sections.append(
            Section(
                title=current_title,
                level=current_level,
                content="\n".join(current_lines).strip(),
            )
        )

    return sections
