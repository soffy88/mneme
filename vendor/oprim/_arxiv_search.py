"""arXiv paper search via public Atom API."""
from __future__ import annotations

import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

_ATOM_NS = "http://www.w3.org/2005/Atom"


@dataclass
class ArxivPaper:
    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]
    pdf_url: str
    published: str  # YYYY-MM-DD
    categories: list[str] = field(default_factory=list)


def arxiv_search(
    *,
    categories: list[str] | None = None,
    keywords: str | None = None,
    author: str | None = None,
    after_date: str | None = None,
    max_results: int = 10,
    rate_limit_sleep: float = 1.0,
) -> list[ArxivPaper]:
    """Query arXiv Atom API and return a list of ArxivPaper objects.

    Args:
        categories: arXiv category codes, e.g. ["q-fin.TR", "cs.LG"].
        keywords:   keyword string searched in title and abstract.
        author:     author name filter.
        after_date: ISO date string (YYYY-MM-DD); exclude papers before this date.
        max_results: maximum results to fetch.
        rate_limit_sleep: seconds to sleep before request (be polite to arXiv).
    """
    parts: list[str] = []
    if categories:
        cat_q = " OR ".join(f"cat:{c}" for c in categories)
        parts.append(f"({cat_q})" if len(categories) > 1 else cat_q)
    if keywords:
        parts.append(f"(ti:{keywords} OR abs:{keywords})")
    if author:
        parts.append(f"au:{author}")
    query = " AND ".join(parts) if parts else "all:*"

    if rate_limit_sleep > 0:
        time.sleep(rate_limit_sleep)

    url = (
        "http://export.arxiv.org/api/query"
        f"?search_query={urllib.request.quote(query)}"
        f"&max_results={max_results}"
        "&sortBy=submittedDate&sortOrder=descending"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "oprim/1.0"})
    data = urllib.request.urlopen(req, timeout=20).read().decode("utf-8")

    root = ET.fromstring(data)
    papers: list[ArxivPaper] = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        raw_id = entry.findtext(f"{{{_ATOM_NS}}}id", "")
        arxiv_id = raw_id.split("/abs/")[-1].split("v")[0].strip()
        if not arxiv_id:
            continue
        title = (entry.findtext(f"{{{_ATOM_NS}}}title") or "").strip().replace("\n", " ")
        abstract = (entry.findtext(f"{{{_ATOM_NS}}}summary") or "").strip()
        published = (entry.findtext(f"{{{_ATOM_NS}}}published") or "")[:10]
        if after_date and published < after_date:
            continue
        authors = [
            a.findtext(f"{{{_ATOM_NS}}}name") or ""
            for a in entry.findall(f"{{{_ATOM_NS}}}author")
        ]
        cats = [
            t.get("term", "")
            for t in entry.findall(f"{{{_ATOM_NS}}}category")
        ]
        papers.append(ArxivPaper(
            arxiv_id=arxiv_id,
            title=title,
            abstract=abstract,
            authors=authors,
            pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
            published=published,
            categories=cats,
        ))
    return papers
