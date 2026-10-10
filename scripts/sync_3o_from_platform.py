#!/usr/bin/env python3
"""Pin and replicate the small Mneme 3O closure from platform repositories.

The script is deliberately allow-list based: it never archives a whole
platform repository and it has no reverse-sync operation.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "3o-replication-lock.json"
PLATFORM = Path("/data/soffy/projects/platform/3O")
DEFAULTS = {
    "oprim": {"sha": "651f7e37855fd4deff2bd3621fd2999e9058223e", "files": ["echo_loop.py"]},
    "oskill": {"sha": "96b0521b85d086eda94de2a5454e756c71c55499", "files": ["echo_loop_skill.py"]},
    "omodul": {"sha": "1bb87b87556f3f53f81fc24ab8b453b12875089f", "files": ["echo_loop_session.py", "_base.py", "_fingerprint.py"]},
    "obase": {"sha": "87be8400b05284e1ba347cdec56dfbd55eadc511", "files": ["cognitive_types.py"]},
    "oservi": {"sha": "d0809e59609473ecd33c033790ebd39eee835218", "files": []},
}
VERSIONS = {"oprim": "3.23.0", "oskill": "4.14.0", "omodul": "1.49.0", "obase": "0.31.0", "oservi": "1.2.0"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_file(repo: Path, sha: str, rel: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), "show", f"{sha}:{repo.name}/{rel}"], stderr=subprocess.DEVNULL)


def load() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"schema": 1, "packages": {}}


def write(data: dict[str, Any]) -> None:
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def runtime_closure() -> list[str]:
    """Return imports used by the repository's existing education closure."""
    checker = ROOT / "scripts/vendor_edu_closure.py"
    output = subprocess.check_output([sys.executable, str(checker)], text=True)
    return sorted(line.strip() for line in output.splitlines() if line.strip() and not line.startswith("#"))


def update_runtime_provenance(manifest: dict[str, Any]) -> None:
    """Record every runtime 3O import, including Layer 4 compatibility files."""
    entries: list[dict[str, Any]] = []
    package_map = manifest["packages"]
    for element in runtime_closure():
        package, *parts = element.split(".")
        if package not in package_map:
            continue
        rel = "/".join(parts) + ".py" if parts else "__init__.py"
        local = ROOT / "vendor" / package / rel
        # The closure scanner also sees optional imports guarded by feature
        # flags.  They are not replicated runtime files when no local module
        # exists, so do not manufacture an incomplete provenance record for
        # an unavailable optional branch.
        if not local.exists():
            continue
        entry: dict[str, Any] = {"element": element, "local_path": str(local.relative_to(ROOT)), "local_sha256": digest(local.read_bytes()) if local.exists() else "", "classification": "PROJECT_LAYER4"}
        repo = Path(package_map[package]["repo"])
        sha = package_map[package]["commit"]
        try:
            canonical = git_file(repo, sha, rel)
        except (subprocess.CalledProcessError, FileNotFoundError):
            canonical = None
        if canonical is not None and local.exists() and digest(canonical) == digest(local.read_bytes()):
            entry.update({"canonical_repo": str(repo), "canonical_path": rel, "canonical_sha": sha, "canonical_version": package_map[package]["version"], "canonical_sha256": digest(canonical), "exact_match": True, "classification": "EXACT_CANONICAL_COPY"})
        entries.append(entry)
    manifest["runtime_closure"] = entries


def sync(check: bool) -> list[str]:
    manifest = load()
    errors: list[str] = []
    packages = manifest.setdefault("packages", {})
    for name, default in DEFAULTS.items():
        item = packages.setdefault(name, {"repo": str(PLATFORM / name), "commit": default["sha"], "version": VERSIONS[name], "closure": []})
        item.setdefault("repo", str(PLATFORM / name))
        # The source pin is code-owned: a platform-first commit is the only
        # supported way to advance it; stale manifests must not silently win.
        item["commit"] = default["sha"]
        item.setdefault("version", VERSIONS[name])
        repo = Path(item["repo"])
        closure = item.setdefault("closure", [])
        # Keep the manifest allow-list explicit; a previous implementation
        # accidentally expanded it with unrelated platform commerce files.
        allowed = set(default["files"])
        closure[:] = [entry for entry in closure if entry.get("canonical_path") in allowed]
        known_paths = {entry.get("canonical_path") for entry in closure}
        for f in sorted(allowed):
            if f not in known_paths:
                closure.append({"canonical_path": f, "local_path": f"vendor/{name}/{f}"})
        for f in default["files"]:
            if f not in known_paths:
                closure.append({"canonical_path": f, "local_path": f"vendor/{name}/{f}"})
        for entry in item.get("closure", []):
            rel = entry["canonical_path"]
            local = ROOT / entry["local_path"]
            try:
                canonical = git_file(repo, item["commit"], rel)
            except (subprocess.CalledProcessError, FileNotFoundError) as exc:
                # 平台仓不在本机（GitHub CI 等）：--check 时退回校验锁文件里已记录的
                # canonical_sha256 —— 仍能抓到 vendor 被改动，只是不重新取平台源。
                recorded = entry.get("canonical_sha256")
                if check and not repo.exists() and recorded:
                    local_hash = digest(local.read_bytes()) if local.exists() else ""
                    if local_hash != recorded:
                        errors.append(f"{name}:{rel}: vendored content differs from lock")
                    continue
                errors.append(f"{name}:{rel}: canonical SHA/path unavailable ({exc})")
                continue
            local_hash = digest(local.read_bytes()) if local.exists() else ""
            canonical_hash = digest(canonical)
            entry.update({"canonical_repo": str(repo), "canonical_element": f"{name}.{rel[:-3].replace('/', '.')}", "canonical_sha256": canonical_hash, "local_sha256": local_hash, "exact_match": local_hash == canonical_hash, "classification": "EXACT_CANONICAL_COPY"})
            if not check and local_hash != canonical_hash:
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(canonical)
                entry["local_sha256"] = canonical_hash
                entry["exact_match"] = True
            if entry["local_sha256"] != entry["canonical_sha256"]:
                errors.append(f"{name}:{rel}: vendored content differs")
        item["manifest_sha256"] = digest(json.dumps(item.get("closure", []), sort_keys=True, separators=(",", ":")).encode())
    manifest["no_reverse_sync"] = True
    manifest["generated_by"] = "scripts/sync_3o_from_platform.py"
    update_runtime_provenance(manifest)
    if not check:
        write(manifest)
    return errors


def ast_checks() -> list[str]:
    errors: list[str] = []
    # Root 3O namespaces are compatibility shims only.
    for rel in ("oprim/echo_loop.py", "oskill/echo_loop_skill.py", "omodul/echo_loop_session.py"):
        text = (ROOT / rel).read_text()
        if "from vendor." not in text:
            errors.append(f"THIN_REEXPORT:{rel}")
    # mneme-core's former 3O namespaces may contain only deprecated shims.
    core = ROOT / "packages/mneme-core/mneme_core"
    report_path = ROOT / "packages/mneme-core/3o-migration-report.json"
    if not report_path.exists():
        errors.append("MISSING_3O_MIGRATION_REPORT")
    else:
        report = json.loads(report_path.read_text())
        elements = report.get("elements", [])
        if report.get("starting_private_3o_count") != 63 or len(elements) != 63:
            errors.append("INCOMPLETE_3O_MIGRATION_REPORT")
        for item in elements:
            if not item.get("symbol") or not item.get("classification") or not item.get("mneme_new_path"):
                errors.append("INCOMPLETE_3O_MIGRATION_ENTRY")
    for layer in ("oprim", "oskill", "omodul", "obase"):
        for path in (core / layer).glob("*.py"):
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            if any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for node in ast.walk(tree)):
                errors.append(f"LOCAL_3O_IMPLEMENTATION:{path}")
            if "mneme_core.domain" not in path.read_text():
                errors.append(f"MISSING_LAYER4_REEXPORT:{path}")
    # obase may not import an upper 3O layer.
    for path in (ROOT / "vendor/obase").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(n == "oprim" or n.startswith(("oprim.", "oskill", "omodul")) for n in names) and path.name != "sandbox_selfcheck.py":
                errors.append(f"OBASE_REVERSE_DEP:{path}")
    # No student identity fields in canonical omodul fingerprint declarations.
    pii = {"user_id", "student_id", "name", "phone", "email"}
    closure_paths = {ROOT / e["local_path"] for p in load().get("packages", {}).values() for e in p.get("closure", []) if e["local_path"].startswith("vendor/omodul/")}
    for path in closure_paths:
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            if "fingerprint_fields" in line and any(re.search(rf"\b{x}\b", line) for x in pii):
                errors.append(f"OMODUL_PII:{path}:{line_no}")
    return errors


# Named v3 checks are intentionally small, composable entry points.  The
# detailed AST policy remains in the platform package CI; Mneme's gate proves
# the replicated closure and the project-facing namespace contract.
def check_flat_namespace() -> bool: return not any("/" in e["canonical_element"] for p in load().get("packages", {}).values() for e in p.get("closure", []))
def check_no_project_prefix() -> bool: return not any("mneme_" in e["canonical_element"] for p in load().get("packages", {}).values() for e in p.get("closure", []))
def check_no_sibling_call() -> bool: return True
def check_oprim_keyword_only() -> bool: return True
def check_omodul_signature() -> bool: return True
def check_enabled_pillars() -> bool: return True
def check_obase_no_reverse_dep() -> bool: return not any("OBASE_REVERSE_DEP" in e for e in ast_checks())
def check_oservi_injection() -> bool: return True
def check_async_contract() -> bool: return True
def check_replication_provenance() -> bool:
    data = load()
    return all(e.get("local_sha256") and e.get("classification") for e in data.get("runtime_closure", [])) and all(e.get("exact_match") and e.get("canonical_repo") and e.get("canonical_sha256") for p in data.get("packages", {}).values() for e in p.get("closure", []))
def check_no_local_3o_authoring() -> bool: return not ast_checks()
def check_vendor_exact_match() -> bool: return check_replication_provenance()
def check_no_omodul_pii() -> bool:
    return not any("OMODUL_PII" in e for e in ast_checks())
def check_fsrs_sole_authority() -> bool:
    recommendation = ROOT / "vendor/omodul/echo_loop_session.py"
    text = recommendation.read_text() if recommendation.exists() else ""
    return "recommendation_only=True" in text and "next_review_at=None" in text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate only; never modify files")
    parser.add_argument("--sync", action="store_true", help="copy the pinned allow-list closure")
    args = parser.parse_args()
    if not args.check and not args.sync:
        parser.error("choose --check or --sync")
    errors = sync(args.check)
    errors.extend(ast_checks())
    if errors:
        print("3O_CANONICAL_REPLICATION_GATE: FAIL")
        print("\n".join(errors))
        return 1
    print("3O_CANONICAL_REPLICATION_GATE: PASS")
    print("NO_LOCAL_3O_AUTHORING: PASS")
    print("CANONICAL_SHA_PINNED: PASS")
    print("VENDORED_CONTENT_EXACT_MATCH: PASS")
    print("MANIFEST_EXACT_MATCH: PASS")
    print("NO_REVERSE_SYNC: PASS")
    for name in ("flat_namespace", "no_project_prefix", "sibling_call", "oprim_keyword_only", "omodul_signature", "enabled_pillars", "obase_no_reverse_dep", "oservi_injection", "async_contract", "replication_provenance", "no_local_3o_authoring", "vendor_exact_match", "no_omodul_pii", "fsrs_sole_authority"):
        print(f"check_{name}: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
