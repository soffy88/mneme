"""Small tracked-file secret safety scan; no external service is required."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
_TOKEN = re.compile(r"(?:ghp_|github_pat_|sk-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})")
_ENV_SECRET = re.compile(r"^\s*(?:JWT_SECRET|MINIO_SECRET_KEY|POSTGRES_PASSWORD|SMTP_PASSWORD)\s*=\s*(\S+)", re.I)
_SAFE_VALUES = {"\"\"", "''", "your_key_here", "your-secret-key-here", "change-me", "changeme", "mneme-dev-secret-change-in-prod!", "minioadmin", "postgres"}


def _is_secret_reference(value: str) -> bool:
    """Allow shell indirection while continuing to reject literal secrets."""

    unquoted = value.strip("\"'")
    return unquoted.startswith("${") or unquoted.startswith("$(")


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    return [root / raw for raw in result.stdout.decode().split("\0") if raw]


def scan_text(path: Path, text: str) -> list[str]:
    findings: list[str] = []
    if path.name != "secret_scan.py" and "vendor" not in path.parts and (_PRIVATE_KEY.search(text) or _TOKEN.search(text)):
        findings.append(f"credential marker in {path}")
    if path.name.startswith(".env") and path.name != ".env.example":
        findings.append(f"tracked environment file {path}")
    for line_number, line in enumerate(text.splitlines(), 1):
        match = _ENV_SECRET.match(line)
        if (
            match
            and match.group(1).strip('"\'') not in _SAFE_VALUES
            and not _is_secret_reference(match.group(1))
        ):
            findings.append(f"non-placeholder secret assignment in {path}:{line_number}")
    return findings


def scan_repository(root: Path | None = None) -> list[str]:
    base = (root or Path(__file__).resolve().parents[1]).resolve()
    findings: list[str] = []
    for path in tracked_files(base):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(scan_text(path.relative_to(base), text))
    return findings


def main() -> int:
    findings = scan_repository()
    if findings:
        print("SECRET SCAN FAILED")
        print("\n".join(findings))
        return 1
    print("SECRET SCAN PASS (tracked files; external secret stores not inspected)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
