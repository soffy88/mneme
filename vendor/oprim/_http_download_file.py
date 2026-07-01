"""Simple HTTP file downloader with optional progress and retry."""
from __future__ import annotations

import time
import urllib.request
from pathlib import Path


def http_download_file(
    url: str,
    dest_path: str | Path,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
    retries: int = 2,
    retry_sleep: float = 3.0,
    rate_limit_sleep: float = 0.0,
    force_ipv4: bool = False,
) -> bool:
    """Download *url* to *dest_path*.

    Returns True on success, False on failure (after all retries).
    """
    if rate_limit_sleep > 0:
        time.sleep(rate_limit_sleep)

    h = {"User-Agent": "oprim/1.0"}
    if headers:
        h.update(headers)

    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            dest.write_bytes(data)
            return True
        except Exception:
            if attempt < retries:
                time.sleep(retry_sleep)
    return False
