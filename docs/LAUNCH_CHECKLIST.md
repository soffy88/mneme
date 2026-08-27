# First-user Launch Checklist

Status values are `PASS`, `BLOCKED`, `OWNER`, or `NOT_APPLICABLE`. Owner and legal items must not be auto-marked PASS.

## RELEASE FREEZE

- PASS — Feature development is frozen for `v0.1.0-rc1`.
- PASS — Only P0 launch-blocker, security, deployment, data-loss, privacy, or critical UX fixes may change this release.
- PASS — No new architecture, readiness framework, analytics framework, or product scope is authorized during the freeze.
- OWNER — Any exception to the freeze requires an explicit owner decision and a new release candidate.

## ENGINEERING

- PASS — production config validation and secret scan
- PASS — health/readiness, safe errors, upload limits, idempotency contracts
- PASS — first-user, returning-user, failure and purge contract tests
- PASS — pilot/product readiness gates

## INFRASTRUCTURE

- OWNER/INFRA — production database revision and migration approval
- OWNER/INFRA — backup/restore drill, RPO/RTO, Redis, object storage, rate limiting, monitoring
- OWNER/INFRA — deploy/rollback mechanism and frontend API origin
- BLOCKED_INFRA — no separate production-like staging environment was available for this closure run; the local compose stack is not evidence of staging.

## PRIVACY / LEGAL

- OWNER/LEGAL — privacy notice, minor-data policy, guardian consent and research determination
- PASS — code purge/export boundaries and no synthetic evidence promotion

## PILOT

- OWNER — protocol/cohort/assignment approval and consent process
- BLOCKED — no real pilot data exists yet

## PRODUCT

- PASS — core Learn Now path remains available without billing
- OWNER — first-user support, content scope, user communication and allowlist

## OPERATIONS

- OWNER/INFRA — on-call ownership, alert routing, incident rehearsal and production access review

## RELEASE DECISION

- BLOCKED_INFRA — staging deployment, staging migration, staging golden paths, staging restore drill, and staging telemetry verification are not complete.
- BLOCKED_OWNER — production secrets, early-access test allowlist, launch owner, support process, and explicit rollout approval are not supplied.
- BLOCKED — legal and consent gates are intentionally unapproved until the owner records a decision in `docs/OWNER-LEGAL-GATE.md`.
