from __future__ import annotations


def preserve_indentation(original: str, *, new: str) -> str:
    """Apply original's leading indentation to new text, preserving relative levels."""
    if not new:
        return new
    # Find first non-empty line in original
    base_indent = ""
    for line in original.splitlines():
        if line.strip():
            base_indent = line[: len(line) - len(line.lstrip())]
            break
    if not base_indent:
        return new
    # Detect new's own base indent (first non-empty line)
    new_lines = new.splitlines(keepends=True)
    new_base = ""
    for line in new_lines:
        stripped = line.rstrip("\n\r")
        if stripped.strip():
            new_base = stripped[: len(stripped) - len(stripped.lstrip())]
            break
    result = []
    for line in new_lines:
        stripped_line = line.rstrip("\n\r")
        ending = line[len(stripped_line):]
        if not stripped_line.strip():
            result.append(line)
            continue
        # Remove new's own base indent, add original's base indent
        if stripped_line.startswith(new_base):
            relative = stripped_line[len(new_base):]
        else:
            relative = stripped_line.lstrip()
        result.append(base_indent + relative + ending)
    return "".join(result)
