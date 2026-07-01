"""oprim.backlink_resolver — Resolve [[wikilink]] references and build backlink index.

3O layer: oprim (single atomic parse, pure logic, no LLM).
Parses wikilink [[Target]] syntax, returns forward + reverse link maps.
"""

from __future__ import annotations

import re


def backlink_resolver(
    *,
    documents: dict[str, str],  # {doc_id: content}
    link_pattern: str = r"\[\[([^\]]+)\]\]",
) -> dict:
    """Parse wikilinks in documents, build forward and backlink index.

    Returns: {
        forward_links: {doc_id: [target_id, ...]},
        backlinks: {target_id: [source_doc_id, ...]},
        unresolved: [target_id, ...],  # linked but no document exists
        total_links: int,
    }
    """
    forward_links: dict[str, list[str]] = {}
    backlinks: dict[str, list[str]] = {}
    total_links = 0

    try:
        compiled = re.compile(link_pattern)
    except re.error as exc:
        # Return empty result with no error field (per spec — no error key defined)
        return {
            "forward_links": {},
            "backlinks": {},
            "unresolved": [],
            "total_links": 0,
        }

    doc_ids = set(documents.keys())

    for doc_id, content in documents.items():
        matches = compiled.findall(content)
        # Deduplicate per source doc (each target counted once per source)
        seen_targets: set[str] = set()
        targets: list[str] = []
        for target in matches:
            target = target.strip()
            if target and target not in seen_targets:
                seen_targets.add(target)
                targets.append(target)

        forward_links[doc_id] = targets
        total_links += len(targets)

        for target in targets:
            if target not in backlinks:
                backlinks[target] = []
            backlinks[target].append(doc_id)

    # Unresolved: targets that have no corresponding document
    all_targets: set[str] = set()
    for targets in forward_links.values():
        all_targets.update(targets)
    unresolved = sorted(all_targets - doc_ids)

    return {
        "forward_links": forward_links,
        "backlinks": backlinks,
        "unresolved": unresolved,
        "total_links": total_links,
    }
