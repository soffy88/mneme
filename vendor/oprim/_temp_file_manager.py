from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from oprim._exceptions import OprimError


class TempFileResult(BaseModel):
    action: str
    file_path: str | None = None
    cleaned_count: int = 0
    success: bool = True
    message: str = ""


_TTL_SECONDS = 30 * 60  # 30 minutes

# In-memory registry: {file_path_str: (created_at, user_key_hash)}
_temp_registry: dict[str, tuple[float, str | None]] = {}


def temp_file_manager(
    *,
    action: Literal["create", "get", "cleanup_expired", "cleanup_user"],
    file_path: Path | None = None,
    user_key_hash: str | None = None,
    suffix: str = ".tmp",
) -> TempFileResult:
    """Manage temporary files with TTL-based expiry.

    Actions:
        create: Create a new temp file and register it. Returns file_path.
        get: Check if a temp file is still valid (not expired). Returns file_path or None.
        cleanup_expired: Delete all files past TTL. Returns cleaned_count.
        cleanup_user: Delete all temp files for a given user_key_hash.

    Args:
        action: Operation to perform
        file_path: Required for "get". Path of the temp file to check.
        user_key_hash: User identifier for per-user operations
        suffix: File suffix for "create" (default ".tmp")

    Returns:
        TempFileResult with outcome details

    Raises:
        OprimError: Invalid action or missing required args
    """
    now = time.monotonic()

    if action == "create":
        try:
            import os

            fd, path_str = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
            _temp_registry[path_str] = (now, user_key_hash)
            return TempFileResult(action="create", file_path=path_str, success=True)
        except OSError as e:
            raise OprimError(f"temp_file_manager create failed: {e}") from e

    elif action == "get":
        if file_path is None:
            raise OprimError("temp_file_manager get: file_path required")
        path_str = str(file_path)
        if path_str not in _temp_registry:
            return TempFileResult(action="get", file_path=None, success=False, message="not_found")
        created_at, _ = _temp_registry[path_str]
        if now - created_at > _TTL_SECONDS:
            _temp_registry.pop(path_str, None)
            return TempFileResult(action="get", file_path=None, success=False, message="expired")
        return TempFileResult(action="get", file_path=path_str, success=True)

    elif action == "cleanup_expired":
        expired = [
            p for p, (created_at, _) in _temp_registry.items() if now - created_at > _TTL_SECONDS
        ]
        cleaned = 0
        for path_str in expired:
            _temp_registry.pop(path_str, None)
            try:
                Path(path_str).unlink(missing_ok=True)
                cleaned += 1
            except OSError:
                pass
        return TempFileResult(action="cleanup_expired", cleaned_count=cleaned, success=True)

    elif action == "cleanup_user":
        if user_key_hash is None:
            raise OprimError("temp_file_manager cleanup_user: user_key_hash required")
        user_files = [p for p, (_, ukh) in _temp_registry.items() if ukh == user_key_hash]
        cleaned = 0
        for path_str in user_files:
            _temp_registry.pop(path_str, None)
            try:
                Path(path_str).unlink(missing_ok=True)
                cleaned += 1
            except OSError:
                pass
        return TempFileResult(action="cleanup_user", cleaned_count=cleaned, success=True)

    else:
        raise OprimError(f"temp_file_manager: unknown action {action!r}")
