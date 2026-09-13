#!/usr/bin/env python3
"""Generate the immutable, registry-backed release manifest used by CI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--code-sha", required=True)
    parser.add_argument("--built-at", required=True)
    parser.add_argument("--backend-repository", required=True)
    parser.add_argument("--worker-repository", required=True)
    parser.add_argument("--beat-repository", required=True)
    parser.add_argument("--backend-digest", required=True)
    parser.add_argument("--frontend-repository", required=True)
    parser.add_argument("--frontend-digest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    data = {
        "schema": "mneme.release.manifest/v2",
        "release_version": args.version,
        "code_release_sha": args.code_sha,
        "built_at": args.built_at,
        "source_repository": "https://github.com/soffy88/mneme",
        "images": [
            {"name": name, "repository": repo, "digest": digest}
            for name, repo, digest in (
                ("api", args.backend_repository, args.backend_digest),
                ("worker", args.worker_repository, args.backend_digest),
                ("beat", args.beat_repository, args.backend_digest),
                ("frontend", args.frontend_repository, args.frontend_digest),
            )
        ],
        "artifact_persistence_gate": "fresh_pull_by_digest_required",
        "runtime_delta_vs_rc5": "NONE",
        "production_deployed": False,
        "rc6_qualified": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
