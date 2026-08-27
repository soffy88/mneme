# First-user Launch Checklist

Status values are `PASS`, `BLOCKED`, `OWNER`, or `NOT_APPLICABLE`. Owner and legal items must not be auto-marked PASS.

## ENGINEERING

- PASS — production config validation and secret scan
- PASS — health/readiness, safe errors, upload limits, idempotency contracts
- PASS — first-user, returning-user, failure and purge contract tests
- PASS — pilot/product readiness gates

## INFRASTRUCTURE

- OWNER/INFRA — production database revision and migration approval
- OWNER/INFRA — backup/restore drill, RPO/RTO, Redis, object storage, rate limiting, monitoring
- OWNER/INFRA — deploy/rollback mechanism and frontend API origin

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
