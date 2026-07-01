"""Lint rules for Stratum repository consistency (Phase 1 rules per STRATUM_SPEC §9)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from oprim._logging import log
from oprim.meta_db import open_meta_db

from oskill.knowledge._context import meta_db_path
from oskill.knowledge.classify_inbox_file import MEDIUMS

_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")
_STORAGE_SLUG_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}--[a-z0-9\-]+\.[a-zA-Z0-9]+$")


@dataclass
class LintIssue:
    severity: str
    rule: str
    target_id: str
    message: str


async def lint(scope: str = "all") -> list[LintIssue]:
    """Check Stratum repository consistency.

    Returns list of LintIssue (empty = clean).
    """
    db_p = meta_db_path()
    if not db_p.exists():
        log.info("oskill.lint.no_db", path=str(db_p))
        return []

    try:
        db = open_meta_db(db_p)
    except Exception as e:
        log.warning("oskill.lint.db_open_failed", error=str(e))
        return [LintIssue("error", "db_open", "meta.duckdb", str(e))]

    issues: list[LintIssue] = []

    if scope in ("all", "substrate"):
        issues.extend(_lint_substrate(db))

    if scope in ("all", "derivative"):
        issues.extend(_lint_derivative(db))

    if scope in ("all", "concept"):
        issues.extend(_lint_concept(db))

    if scope in ("all", "note"):
        issues.extend(_lint_note(db))

    db.close()
    log.info("oskill.lint.done", scope=scope, issues=len(issues))
    return issues


def _lint_substrate(db) -> list[LintIssue]:
    issues = []
    rows = db.fetchall("SELECT id, meta_json, source_path FROM substrates")
    for sid, meta_json_str, source_path in rows:
        if not _ULID_RE.match(sid or ""):
            issues.append(LintIssue("error", "ulid_format", sid, f"Invalid ULID: {sid!r}"))
        try:
            meta = json.loads(meta_json_str) if meta_json_str else {}
        except Exception:
            meta = {}
        medium = meta.get("medium")
        if medium not in MEDIUMS:
            issues.append(
                LintIssue(
                    "error",
                    "schema_consistency",
                    sid,
                    f"Invalid medium: {medium!r} (not in 18 mediums)",
                )
            )
        if source_path:
            fname = source_path.split("/")[-1]
            if not _STORAGE_SLUG_RE.match(fname):
                issues.append(
                    LintIssue(
                        "warning",
                        "filename_format",
                        sid,
                        f"Filename does not match {{ulid}}--{{slug}}.{{ext}}: {fname!r}",
                    )
                )
    return issues


def _lint_derivative(db) -> list[LintIssue]:
    issues = []
    substrate_ids = {r[0] for r in db.fetchall("SELECT id FROM substrates")}
    rows = db.fetchall("SELECT id, substrate_id FROM derivative")
    for did, sub_id in rows:
        if sub_id not in substrate_ids:
            issues.append(
                LintIssue(
                    "error",
                    "reference_integrity",
                    did,
                    f"derivative.substrate_id {sub_id!r} not found in substrates",
                )
            )
    return issues


def _lint_concept(db) -> list[LintIssue]:
    issues = []
    substrate_ids = {r[0] for r in db.fetchall("SELECT id FROM substrates")}
    try:
        rows = db.fetchall("SELECT id, source_ids FROM concepts")
    except Exception:
        return issues
    for cid, refs_json in rows:
        if not refs_json:
            continue
        try:
            refs = json.loads(refs_json) if isinstance(refs_json, str) else refs_json
        except Exception:
            continue
        for ref in refs or []:
            if ref not in substrate_ids:
                issues.append(
                    LintIssue(
                        "error",
                        "reference_integrity",
                        cid,
                        f"concept.source_ids contains unknown substrate: {ref!r}",
                    )
                )
    return issues


def _lint_note(db) -> list[LintIssue]:
    issues = []
    substrate_ids = {r[0] for r in db.fetchall("SELECT id FROM substrates")}
    try:
        rows = db.fetchall("SELECT id, substrate_refs, concept_refs FROM notes")
    except Exception:
        return issues
    for nid, sub_refs_json, _ in rows:
        if not sub_refs_json:
            continue
        try:
            refs = json.loads(sub_refs_json) if isinstance(sub_refs_json, str) else sub_refs_json
        except Exception:
            continue
        for ref in refs or []:
            if ref not in substrate_ids:
                issues.append(
                    LintIssue(
                        "error",
                        "reference_integrity",
                        nid,
                        f"note.substrate_refs contains unknown substrate: {ref!r}",
                    )
                )
    return issues
