"""P-validate_html: sandboxed HTML safety check (no LLM, no IO)."""
from __future__ import annotations

import re

from oprim._animation_types import HtmlValidationResult

# Danger pattern regexes
_INLINE_EVENT_RE = re.compile(r'\bon\w+\s*=', re.IGNORECASE)
_JAVASCRIPT_URI_RE = re.compile(
    r'''(?:href|src|action|data)\s*=\s*["']?\s*javascript\s*:''',
    re.IGNORECASE,
)
_EVAL_RE = re.compile(r'\beval\s*\(', re.IGNORECASE)
_FETCH_RE = re.compile(r'\bfetch\s*\(', re.IGNORECASE)
_XHR_RE = re.compile(r'\bXMLHttpRequest\b')
_SCRIPT_EXT_RE = re.compile(
    r'<script[^>]+\bsrc\s*=\s*["\']https?://[^"\']+["\']',
    re.IGNORECASE | re.DOTALL,
)
_IFRAME_EXT_RE = re.compile(
    r'<iframe[^>]+\bsrc\s*=\s*["\']https?://[^"\']+["\']',
    re.IGNORECASE | re.DOTALL,
)
_EXTERNAL_SRC_RE = re.compile(r'\bsrc\s*=\s*["\']https?://[^"\']+["\']', re.IGNORECASE)


def validate_html(*, html: str, allow_external_src: bool = False) -> HtmlValidationResult:
    """Scan html for unsafe patterns. Pure function — no LLM, no IO.

    Detected patterns:
      external_script_src    <script src="http://...">
      inline_event_handler   onerror=, onload=, onclick=, … attribute
      eval_usage             eval( anywhere in content
      javascript_uri         href/src/action="javascript:..."
      external_iframe        <iframe src="http://...">
      fetch_usage            fetch( anywhere in content
      xmlhttprequest_usage   XMLHttpRequest anywhere in content
      external_src           any src="http://..." (only when allow_external_src=False)

    Returns HtmlValidationResult(is_safe, violations, sanitized).
    sanitized is None when html is safe; otherwise the html with dangerous
    patterns neutralised (best-effort — not a full HTML sanitiser).
    """
    if not html or not html.strip():
        return HtmlValidationResult(is_safe=True, violations=[], sanitized=None)

    violations: list[str] = []
    sanitized = html

    if _SCRIPT_EXT_RE.search(html):
        violations.append("external_script_src")
        sanitized = _SCRIPT_EXT_RE.sub('<script data-blocked="external_src">', sanitized)

    if _INLINE_EVENT_RE.search(html):
        violations.append("inline_event_handler")
        sanitized = _INLINE_EVENT_RE.sub('data-blocked-event=', sanitized)

    if _EVAL_RE.search(html):
        violations.append("eval_usage")
        sanitized = _EVAL_RE.sub('__blocked__(', sanitized)

    if _JAVASCRIPT_URI_RE.search(html):
        violations.append("javascript_uri")
        sanitized = re.sub(
            r'''((?:href|src|action|data)\s*=\s*["']?)\s*javascript\s*:''',
            r'\1blocked:',
            sanitized,
            flags=re.IGNORECASE,
        )

    if _IFRAME_EXT_RE.search(html):
        violations.append("external_iframe")
        sanitized = _IFRAME_EXT_RE.sub('<iframe data-blocked="external_src"', sanitized)

    if _FETCH_RE.search(html):
        violations.append("fetch_usage")
        sanitized = _FETCH_RE.sub('__blockedFetch(', sanitized)

    if _XHR_RE.search(html):
        violations.append("xmlhttprequest_usage")
        sanitized = _XHR_RE.sub('__BlockedXHR__', sanitized)

    if not allow_external_src and _EXTERNAL_SRC_RE.search(html):
        violations.append("external_src")
        sanitized = _EXTERNAL_SRC_RE.sub('src="blocked"', sanitized)

    is_safe = len(violations) == 0
    return HtmlValidationResult(
        is_safe=is_safe,
        violations=violations,
        sanitized=None if is_safe else sanitized,
    )
