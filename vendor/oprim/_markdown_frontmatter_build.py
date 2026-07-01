"""oprim.markdown_frontmatter_build — Build YAML frontmatter string."""
from __future__ import annotations
import yaml


def markdown_frontmatter_build(metadata: dict) -> str:
    """Build YAML frontmatter string from metadata dict.

    Args:
        metadata: Dict of frontmatter fields
                  (substrate_id, title, author, doc_type, language, ...).

    Returns:
        String in format "---\\n<yaml>\\n---\\n".

    Raises:
        ValueError: metadata is empty.

    Example:
        >>> fm = markdown_frontmatter_build({"title": "Book", "author": "Author"})
        >>> fm.startswith("---\\n")
        True
    """
    if not metadata:
        raise ValueError("metadata must not be empty")
    body = yaml.dump(metadata, allow_unicode=True, default_flow_style=False).strip()
    return f"---\n{body}\n---\n"
