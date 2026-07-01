from __future__ import annotations


def truncate_for_context(
    text: str, *, max_lines: int = 2000, max_bytes: int = 50_000
) -> str:
    """Truncate text to fit context window, preserving whole characters."""
    if max_lines <= 0 or max_bytes <= 0:
        raise ValueError("max_lines and max_bytes must be > 0")
    if not text:
        return text
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    # Apply line limit
    if total_lines > max_lines:
        kept = lines[:max_lines]
        truncated_lines = total_lines - max_lines
        joined = "".join(kept)
        truncated_bytes = len(text.encode()) - len(joined.encode())
        return joined + f"\n... [truncated {truncated_lines} lines / {truncated_bytes} bytes]"
    # Apply byte limit (safe multi-byte cut)
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # Find safe cut point that doesn't split a multi-byte char
    cut = encoded[:max_bytes]
    while cut and cut[-1] & 0xC0 == 0x80:  # continuation byte
        cut = cut[:-1]
    kept_text = cut.decode("utf-8", errors="replace")
    kept_lines = len(kept_text.splitlines())
    truncated_lines = total_lines - kept_lines
    truncated_bytes = len(encoded) - len(cut)
    return kept_text + f"\n... [truncated {truncated_lines} lines / {truncated_bytes} bytes]"
