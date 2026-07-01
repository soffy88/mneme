from __future__ import annotations

from pathlib import Path

_MIME_MAP: dict[str, str] = {
    ".py": "text/x-python", ".pyi": "text/x-python",
    ".js": "text/javascript", ".mjs": "text/javascript",
    ".ts": "text/typescript", ".tsx": "text/typescript",
    ".html": "text/html", ".htm": "text/html",
    ".css": "text/css",
    ".json": "application/json", ".jsonc": "application/json",
    ".xml": "application/xml",
    ".yaml": "text/yaml", ".yml": "text/yaml",
    ".toml": "application/toml",
    ".md": "text/markdown", ".markdown": "text/markdown",
    ".txt": "text/plain", ".log": "text/plain",
    ".sh": "application/x-sh", ".bash": "application/x-sh",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".pdf": "application/pdf",
    ".zip": "application/zip", ".tar": "application/x-tar",
    ".gz": "application/gzip",
    ".wasm": "application/wasm",
    ".csv": "text/csv", ".tsv": "text/tab-separated-values",
    ".rs": "text/x-rust", ".go": "text/x-go",
    ".c": "text/x-c", ".cpp": "text/x-c++", ".h": "text/x-c",
    ".java": "text/x-java", ".kt": "text/x-kotlin",
    ".rb": "text/x-ruby", ".php": "text/x-php",
    ".r": "text/x-r", ".sql": "application/sql",
    ".ipynb": "application/x-ipynb+json",
}

def detect_mime(path: Path) -> str:
    """Infer MIME type from file extension (pure computation, no disk I/O)."""
    suffix = path.suffix.lower()
    return _MIME_MAP.get(suffix, "application/octet-stream")
