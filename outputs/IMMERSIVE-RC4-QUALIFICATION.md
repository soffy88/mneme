# Mneme v0.1.0-rc4 qualification

Status: **QUALIFIED**
Date: 2026-08-30 UTC
Code release SHA: `a359877676a39fc2627a6f429adea77b0ed41311`
Production deployment: **NO**

## Release gates

- RC3 remained unchanged. RC4 runtime changes are on the release branch and
  the immutable images below all carry the code SHA above.
- Environment contract: PASS — [`docs/ENVIRONMENTS.md`](../docs/ENVIRONMENTS.md).
- Production preflight fail-closed tests: PASS. Production was not invoked;
  identity remains an infrastructure follow-up and is not an RC4 gate.
- Central authenticated-user canary gate and server enforcement: PASS.
  Global default is OFF; the server-only allowlist defaults to empty,
  canonicalizes UUIDs, rejects malformed/wildcard entries, deduplicates, and
  is bounded.
- Full clean-checkout `./scripts/check.sh`: **1355 passed, 0 failed,
  14 skipped, coverage 79.82%**.
- SVG isolation regression: **10/10 focused runs passed**. Root cause was
  completed sandbox children not being deterministically reaped after the
  join timeout, allowing process/resource buildup in long multi-threaded
  runs. The fix terminates/kills only when needed and always joins; no
  skip/xfail or assertion relaxation was used.
- Frontend typecheck and production builds: PASS for `mneme-web` and
  `apps/mneme-studio`.
- npm audit: **0 critical, 0 high, 0 moderate, 0 low** in both full and
  production-only audits. The vulnerable Next.js, PDF.js, EPUB/XML, and
  transitive tar/brace-expansion/js-yaml/postcss chains were remediated with
  the smallest compatible upgrades/overrides and revalidated by typecheck,
  build, and affected reader paths.
- pip-audit: 112 dependencies, 0 vulnerabilities.
- Secret checks: tracked secret scan PASS; gitleaks RC3-to-RC4 delta 0.
  Nine historical findings remain confined to pre-existing old revisions and
  are not part of the RC4 delta.
- Trivy: no RC4-introduced High/Critical findings versus the pinned base
  scans; API delta 0 and frontend delta `-1 critical, -19 high`.
  Misconfigurations and image secrets: 0. Raw inherited findings are recorded
  in the release handoff rather than suppressed.

## Isolated staging

The exact RC4 API, worker, beat, and frontend images were deployed to the
isolated local staging stack. No demo or production data was used. The
temporary local proxy was bound only to loopback.

- Global OFF + empty allowlist: synthetic users A and B both denied.
- Global OFF + canary A: A enabled, B denied.
- B using B's token against A's URL: authorization denied (HTTP 403).
- Global ON: A and B both enabled.
- Final state restored to Global OFF + canary A.
- A completed the HTTP immersive golden path, including media, transcript,
  segments, session, telemetry, practice, events, policy, and explain.
- B's status, media, session, practice, telemetry, and Learn Now paths all
  denied; Learn Now returned no immersive candidate for B.
- Telemetry changed only the telemetry-event count; it created no performance
  Evidence and did not advance LearningEvent, mastery, or FSRS state.
- Existing Mneme core regression (FSRS duplicate guard and purge/idempotency)
  passed against the exact RC4 SHA.
- Browser verification: authenticated A saw enabled immersive capability;
  authenticated B saw disabled capability. Frontend did not read the
  allowlist.

## Soak

Final staging configuration was Global OFF + canary A for 30 minutes, with 30
continuous 60-second API/frontend health samples:

| Metric | Result |
|---|---:|
| API/frontend 5xx samples/log lines | 0 |
| Container restarts | 0 |
| Gate errors | 0 |
| Cognitive projection errors | 0 |
| FSRS errors | 0 |

## Artifact and release identity

API/worker/beat use digest
`sha256:32aec19baf11a7523398fa6b013d09ee65c83c548f732709d430f7dd90007c33`.
Frontend uses digest
`sha256:aefdde6da5a7580ff596dfffa9849f2d66c9705d1c37a8a00e17958628d73495`.
Each image label and staging runtime `GIT_SHA` equals the code release SHA.

The annotated `v0.1.0-rc4` tag targets the final release-metadata commit
containing this qualification, manifest, SBOM reference, and staging audit.
The exact tag object, peeled commit, and remote refs are recorded in the
final release handoff. No production deployment or production immersive
enablement occurred.

`P0=NONE`  `P1=NONE`  `RC4_QUALIFIED=YES`
