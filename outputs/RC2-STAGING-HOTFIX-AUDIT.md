# Mneme RC2 staging hotfix audit

Date: 2026-08-27 UTC
Scope: synthetic staging data only. Production was not deployed and no real
pilot user was used.

## Release identity

- RC1 commit: `a28edb25930232fb7af6150421d12a4237f655f2`
- RC2 commit: `a48c14acf189a03de5eabb2ed0ea3ef4e4d4c725`
- RC2 tag: `v0.1.0-rc2`
- RC1 tag remained unchanged.
- Staging API, worker, beat, and frontend all reported RC2 revision `a48c14acf189a03de5eabb2ed0ea3ef4e4d4c725`.
- PostgreSQL migration: `5e7f8a9b0c12 (head)`
- Pre-RC2 database backup: `backups/pre-rc2-20260827T155535Z.dump`

## P0-1 — review and FSRS

### Root cause

The RC1 cognitive service supplied the massed-practice debounce interval to
review interactions. Mastery projection therefore advanced while the FSRS
projection treated an eligible review as suppressed.

### Fix

The review source now travels through the authoritative cognitive projection.
An eligible, due review removes only the inappropriate debounce for that review,
then invokes the existing FSRS kernel. Event identity is persisted and locked
transactionally so a duplicate event returns the existing result without a
second mastery or FSRS update. Non-due evidence retains the existing debounce.

### Local verification

- Focused hotfix, scheduling, hard-delete, and replay tests: `36 passed`
- Full `./scripts/check.sh`: `1350 passed, 14 skipped, 0 failed`
- Coverage: `81.12%`

### Staging verification

The production-service staging regression runner passed against RC2.

- Mastery: `0.6756756756756757` → `0.9394957983193277`
- FSRS before: stability `2.3065`, difficulty `2.118103970459016`, due `2026-08-25T17:24:37Z`, last review `2026-08-25T17:14:37Z`
- FSRS after: stability `2.3065`, difficulty `2.111214235785395`, due `2026-08-27T19:14:37Z`, last review `2026-08-25T19:14:37Z`
- Duplicate event: detected; attempts unchanged; schedule unchanged
- After restarting API, worker, and beat: persisted FSRS state was readable and the duplicate remained idempotent
- Restart duplicate evidence: attempts `2` → `2`, `schedule_unchanged=true`

## P0-2 — student purge

### Root cause

The old purge order removed `pilot_enrollments` before the
`pilot_assignments` and `pilot_measurement_schedules` rows that reference it
through `NO ACTION` foreign keys.

### Fix

The purge now removes pilot child rows before enrollments, maintains the full
student-linked inventory, verifies the privacy boundary before reporting
success, and fails closed on object-storage cleanup failure. No migration was
required; the existing schema and migration head remain unchanged.

### Staging verification

- Real pilot enrollment, assignment, and measurement schedule: deleted
- Memory claim/evidence and join edge: deleted
- Synthetic textbook artifact row and object: deleted
- Database residual: `{}` / zero rows
- Object residual: zero
- Second purge: `purged_users=0` and successful (idempotent)
- No FK error

## Validation gates

- `./scripts/check.sh`: PASS
- `make web-build`: PASS
- `make pilot-readiness`: PASS
- `make product-readiness`: PASS
- `make launch-readiness`: engineering checks PASS; expected owner/infrastructure launch blocks remain
- `uv lock --check`: PASS
- GitHub Actions quality gate for RC2: PASS (`33089040489`)
- Migration head: PASS

## Safety status

- Internal staging runtime: PASS
- DNS: `BLOCKED_OWNER`
- TLS: `BLOCKED_OWNER`
- External staging ready: NO
- Production deployment: DO NOT DEPLOY
- New P0 blockers: NONE
