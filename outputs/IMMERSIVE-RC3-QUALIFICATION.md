# Mneme v0.1.0-rc3 Qualification

## Release identity

- **CODE_RELEASE_SHA**: `b5d41c32e4ffe52e2ed41902c7345598b8a5549b`
- **RELEASE_METADATA_SHA**: `SELF_TAGGED_COMMIT` (the peeled RC3 commit is authoritative)
- **SOURCE_FEATURE_SHA**: `05377c9b09b7815c8f3ba0362f4619827a08bfb3`
- **STAGING_RUNTIME_SHA**: `0b8bf9f96c8cbb3f9d51e83027f9b9f948f7041e`
- **Alembic head**: `7b2c3d4e5f6a`
- **Feature flag default**: `IMMERSIVE_LEARNING_ENABLED=false`

## Scope and staging evidence

This candidate is the Immersive Learning MVP only. Staging qualification is
referenced by `outputs/IMMERSIVE-STAGING-QUALIFICATION.md` and
`outputs/IMMERSIVE-STAGING-SOAK.json`: 56/56 functional PASS and 30/30 soak
PASS. The report distinguishes source feature SHA from the deployed runtime
SHA. Staging was isolated and production was untouched.

The post-staging diff from `0b8bf9f` to the release candidate contains the
release test-harness fixes and release metadata; the staging audit correction
is metadata-only. The fixes isolate CLI and paper-upload tests from live
services and external object storage without changing their product contracts.

## Gates

- Clean checkout: PASS.
- Fresh database migration to `7b2c3d4e5f6a`: PASS; single head.
- Upgrade fixture `5e7f8a9b0c12` to head: PASS; existing LearningEvent,
  CognitiveState, FSRS, and user data remain available.
- `./scripts/check.sh`: PASS — 1386 passed, 0 failed, 14 skipped, 79.85%
  coverage, 816.22s.
- Ruff: PASS. MyPy: PASS. Frontend typecheck/build: PASS.
- Original seven failures: closed. The selected failures passed 3 consecutive
  times; the visualization failure set passed 10 consecutive times.
- Python dependency audit: PASS (`pip-audit 2.10.1`, locked uv export,
  critical/high/medium/low: 0/0/0/0). npm audit: PASS, 0 vulnerabilities.
- Secret scan and container security review: PASS; no repository credentials,
  private keys, embedded `.env`, or staging credentials found.
- SBOM: PASS — `outputs/RELEASE-SBOM-v0.1.0-rc3.json`.
- API, worker, scheduler, and frontend images: PASS. Each carries the exact
  code-release SHA in OCI/build metadata; digests are recorded in the manifest.
- Isolated RC stack flag-off smoke: PASS (health, readiness, frontend, worker,
  beat, migration, core path, and default-off status).
- Isolated RC stack flag-on smoke: PASS (status, media/transcript/session and
  telemetry HTTP path; immersive targeted suite covers practice, Evidence,
  CognitiveState, Memory Router, FSRS, and resume).
- Telemetry non-advancement: PASS; interaction telemetry remains on the
  telemetry plane and does not create performance evidence or advance mastery.
- Rollback compatibility: PASS for the additive schema with the RC2-compatible
  core paths; no destructive downgrade was performed.

## Deferred capabilities

ASR, pronunciation scoring, a full production LLM explain provider, external
media-provider integrations, and podcast expansion remain deferred. They are
not part of this RC.

## Release decision

No P0 or P1 blockers remain. Production deployment is explicitly out of scope;
the production immersive flag remains OFF. Subject to final main integration,
annotated tag verification, and remote verification, this candidate is
qualified for `v0.1.0-rc3`.
