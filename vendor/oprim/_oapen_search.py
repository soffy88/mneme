"""OAPEN open-access book search via OAPEN REST + Unpaywall PDF resolution."""
from __future__ import annotations

import json
import socket
import time
import urllib.request
import urllib.parse


_TRUSTED_PDF_HOSTS = (
    "link.springer.com",
)

_UNPAYWALL_EMAIL = "soffy88@gmail.com"


def _force_ipv4():
    """Monkey-patch socket.getaddrinfo to prefer IPv4 (OAPEN IPv6 unreachable from CN)."""
    _orig = socket.getaddrinfo

    def ipv4_first(host, port, family=0, type=0, proto=0, flags=0):
        try:
            v4 = [r for r in _orig(host, port, family, type, proto, flags)
                  if r[0] == socket.AF_INET]
            return v4 if v4 else _orig(host, port, family, type, proto, flags)
        except Exception:
            return _orig(host, port, family, type, proto, flags)

    socket.getaddrinfo = ipv4_first
    return _orig


def _restore_getaddrinfo(orig):
    socket.getaddrinfo = orig


def oapen_search(
    *,
    query: str,
    language: str | None = None,
    max_results: int = 10,
    rate_limit_sleep: float = 2.0,
) -> list:
    """Search OAPEN open-access books, resolve PDF via Unpaywall.

    Only returns books where a trusted PDF URL (Springer) is available.
    Returns list[SourceResult].
    """
    from oprim._media_types import SourceResult

    orig_getaddrinfo = _force_ipv4()
    try:
        return _oapen_search_inner(
            query=query,
            language=language,
            max_results=max_results,
            rate_limit_sleep=rate_limit_sleep,
            SourceResult=SourceResult,
        )
    finally:
        _restore_getaddrinfo(orig_getaddrinfo)


def _oapen_search_inner(*, query, language, max_results, rate_limit_sleep, SourceResult):
    if rate_limit_sleep > 0:
        time.sleep(rate_limit_sleep)

    # Step 1: Search OAPEN REST
    params = {"query": query, "limit": str(max_results * 4)}  # fetch more, filter later
    search_url = "https://library.oapen.org/rest/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        search_url, headers={"Accept": "application/json", "User-Agent": "oprim/1.0"}
    )
    try:
        items = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception:
        return []

    results: list = []
    seen_handles: set[str] = set()

    for item in items:
        if len(results) >= max_results:
            break

        uuid = item.get("uuid") or ""
        handle = item.get("handle") or ""
        if not uuid or handle in seen_handles:
            continue
        seen_handles.add(handle)

        # Step 2: Get metadata including DOI
        meta_url = f"https://library.oapen.org/rest/items/{uuid}?expand=metadata"
        mreq = urllib.request.Request(
            meta_url, headers={"Accept": "application/json", "User-Agent": "oprim/1.0"}
        )
        try:
            it = json.loads(urllib.request.urlopen(mreq, timeout=8).read())
        except Exception:
            continue

        mds: dict[str, str] = {}
        for m in (it.get("metadata") or []):
            k = m.get("key") or ""
            if k and k not in mds:
                mds[k] = m.get("value") or ""

        doi = mds.get("oapen.identifier.doi") or mds.get("dc.identifier.doi") or ""
        title = mds.get("dc.title") or item.get("name") or ""
        publisher = mds.get("publisher.name") or mds.get("dc.publisher") or ""

        if not doi or not title:
            continue

        # Step 3: Resolve PDF via Unpaywall
        up_url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi, safe='')}?email={_UNPAYWALL_EMAIL}"
        try:
            time.sleep(0.5)
            up = json.loads(urllib.request.urlopen(up_url, timeout=10).read())
        except Exception:
            continue

        if not up.get("is_oa"):
            continue

        best = up.get("best_oa_location") or {}
        pdf_url = best.get("url_for_pdf") or ""
        if not pdf_url:
            for loc in (up.get("oa_locations") or []):
                u = loc.get("url_for_pdf") or ""
                if u and any(u.startswith(f"https://{h}") for h in _TRUSTED_PDF_HOSTS):
                    pdf_url = u
                    break

        if not pdf_url or not any(
            pdf_url.startswith(f"https://{h}") for h in _TRUSTED_PDF_HOSTS
        ):
            continue

        results.append(
            SourceResult(
                external_id=handle,
                title=title,
                download_url=pdf_url,
                file_type="pdf",
                metadata={
                    "doi": doi,
                    "publisher": publisher,
                    "oapen_handle": handle,
                    "source_type": "oapen",
                },
            )
        )

    return results
