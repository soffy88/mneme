"""oprim.citation_formatter — Format a citation in APA/MLA/Chicago style.

3O layer: oprim (single atomic format, pure logic, no LLM).
Given structured citation data, returns formatted citation string.
"""

from __future__ import annotations


def citation_formatter(
    *,
    citation: dict,
    style: str = "apa",  # "apa" | "mla" | "chicago"
) -> dict:
    """Format a citation dict into a styled string.

    citation keys: authors (list[str]), title, year, journal|publisher,
                   volume, issue, pages, url, doi
    Returns: {formatted: str, style: str, error: str|None}
    """
    result: dict = {
        "formatted": "",
        "style": style,
        "error": None,
    }

    if not citation:
        result["error"] = "empty citation"
        return result

    valid_styles = {"apa", "mla", "chicago"}
    if style not in valid_styles:
        result["error"] = f"unknown style '{style}'; must be one of {sorted(valid_styles)}"
        return result

    try:
        authors: list[str] = citation.get("authors") or []
        title: str = citation.get("title") or ""
        year: str | int | None = citation.get("year")
        journal: str = citation.get("journal") or ""
        publisher: str = citation.get("publisher") or ""
        volume: str = str(citation.get("volume") or "")
        issue: str = str(citation.get("issue") or "")
        pages: str = str(citation.get("pages") or "")
        url: str = citation.get("url") or ""
        doi: str = citation.get("doi") or ""

        year_str = str(year) if year is not None else "n.d."

        if style == "apa":
            formatted = _format_apa(
                authors=authors,
                title=title,
                year_str=year_str,
                journal=journal,
                publisher=publisher,
                volume=volume,
                issue=issue,
                pages=pages,
                url=url,
                doi=doi,
            )
        elif style == "mla":
            formatted = _format_mla(
                authors=authors,
                title=title,
                year_str=year_str,
                journal=journal,
                publisher=publisher,
                volume=volume,
                issue=issue,
                pages=pages,
                url=url,
                doi=doi,
            )
        else:  # chicago
            formatted = _format_chicago(
                authors=authors,
                title=title,
                year_str=year_str,
                journal=journal,
                publisher=publisher,
                volume=volume,
                issue=issue,
                pages=pages,
                url=url,
                doi=doi,
            )

        result["formatted"] = formatted.strip()

    except Exception as exc:
        result["error"] = str(exc)

    return result


def _author_apa(authors: list[str]) -> str:
    """Format author list for APA: Last, F. (et al. if >6)."""
    if not authors:
        return ""
    if len(authors) > 6:
        return f"{authors[0]}, et al."
    return ", ".join(authors)


def _author_mla(authors: list[str]) -> str:
    """Format author list for MLA: first author inverted, rest normal."""
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) > 3:
        return f"{authors[0]}, et al."
    return f"{authors[0]}, and {', and '.join(authors[1:])}"


def _author_chicago(authors: list[str]) -> str:
    """Format author list for Chicago: same as MLA."""
    return _author_mla(authors)


def _format_apa(
    *,
    authors: list[str],
    title: str,
    year_str: str,
    journal: str,
    publisher: str,
    volume: str,
    issue: str,
    pages: str,
    url: str,
    doi: str,
) -> str:
    parts: list[str] = []

    author_str = _author_apa(authors)
    if author_str:
        parts.append(f"{author_str}.")

    parts.append(f"({year_str}).")

    if title:
        parts.append(f"{title}.")

    if journal:
        source = journal
        if volume:
            source += f", {volume}"
            if issue:
                source += f"({issue})"
        if pages:
            source += f", {pages}"
        parts.append(f"{source}.")
    elif publisher:
        parts.append(f"{publisher}.")

    if doi:
        parts.append(f"https://doi.org/{doi}")
    elif url:
        parts.append(url)

    return " ".join(parts)


def _format_mla(
    *,
    authors: list[str],
    title: str,
    year_str: str,
    journal: str,
    publisher: str,
    volume: str,
    issue: str,
    pages: str,
    url: str,
    doi: str,
) -> str:
    parts: list[str] = []

    author_str = _author_mla(authors)
    if author_str:
        parts.append(f"{author_str}.")

    if title:
        if journal:
            parts.append(f'"{title}."')
        else:
            parts.append(f"{title}.")

    if journal:
        source = journal
        if volume:
            source += f" vol.{volume}"
            if issue:
                source += f".{issue}"
        source += f" ({year_str})"
        if pages:
            source += f": {pages}"
        parts.append(f"{source}.")
    elif publisher:
        parts.append(f"{publisher}, {year_str}.")

    if doi:
        parts.append(f"https://doi.org/{doi}")
    elif url:
        parts.append(url)

    return " ".join(parts)


def _format_chicago(
    *,
    authors: list[str],
    title: str,
    year_str: str,
    journal: str,
    publisher: str,
    volume: str,
    issue: str,
    pages: str,
    url: str,
    doi: str,
) -> str:
    parts: list[str] = []

    author_str = _author_chicago(authors)
    if author_str:
        parts.append(f"{author_str}.")

    if title:
        if journal:
            parts.append(f'"{title}."')
        else:
            parts.append(f"{title}.")

    if journal:
        source = journal
        if volume:
            source += f" {volume}"
            if issue:
                source += f", no. {issue}"
        source += f" ({year_str})"
        if pages:
            source += f": {pages}"
        parts.append(f"{source}.")
    elif publisher:
        parts.append(f"{publisher}, {year_str}.")

    if doi:
        parts.append(f"https://doi.org/{doi}")
    elif url:
        parts.append(url)

    return " ".join(parts)
