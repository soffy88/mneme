# Production Deployment Runbook

Provider-neutral sequence for an owner/infra-controlled deployment. The repository commands are safety checks; they do not deploy or migrate production.

## Release order

The owner/infra operator must execute these steps against the frozen release SHA. Every service must use the same immutable image or build: backend, frontend, worker, and scheduler may not be mixed across releases.

1. Freeze and record the release SHA and migration head.
2. Confirm owner approval, legal/privacy gates, real secrets, explicit origins, and `MNEME_ENV=production`.
3. Run `make secret-scan` and `make production-db-preflight` through an explicitly approved read-only channel.
4. Confirm a verified database and object-storage backup before any migration. RPO/RTO remain `TBD_OWNER_DECISION` until the owner records them.
5. Enable the approved maintenance/traffic strategy if required by the infrastructure owner.
6. Apply Alembic migrations through the approved production mechanism, then verify the expected head.
7. Deploy the immutable backend image.
8. Deploy the matching worker and scheduler image.
9. Deploy the matching frontend and verify its backend API origin.
10. Verify `/health`, `/readiness`, DB compatibility, storage, worker status, scheduler status, logs, and metrics.
11. Run a non-sensitive smoke path and verify `trace_id` propagation. Do not use synthetic data in production analytics.
12. Monitor the release before enabling controlled early access.
13. Enable the early-access allowlist only after the owner has supplied the approved list and confirmed the feature flags.
14. Enable controlled first-user access. Keep pilot, notifications, and billing off unless separately approved.

## Rollback triggers

Immediately stop early access and begin the normal rollback procedure if any of these occur: evidence corruption, cross-user leakage, purge failure, a wrong student state, duplicate evidence that affects mastery, an unrecoverable migration issue, sustained readiness failure, or an unexplained increase in core-loop failures. Do not continue observing a known integrity or privacy failure.

Rollback means disabling launch-specific flags, routing traffic to the last verified release when compatible, preserving trace and incident evidence, and re-running migration compatibility, `/health`, `/readiness`, and smoke checks. A schema rollback is not automatic; it requires the owner/infra migration runbook and a verified backup.

## Post-launch watch

Observe at 24 hours, 72 hours, and 7 days: request error rate, latency, DB availability, worker failures, projection lag, policy fallback, LLM failures, upload failures, purge failures, first-value completion, core-loop completion, and usable-evidence rate. Product activity must not be used as a substitute for retention, transfer, independent evidence, or learning effect.

## Stop conditions

The operator must set early access to closed if evidence integrity, user isolation, deletion, state correctness, or migration recoverability is in doubt. Escalate to the owner and preserve the relevant `trace_id`; do not fabricate a result or repair an event by editing cognitive state directly.

Production migration, backup restore, secret provisioning, external rate limiting, and deployment remain `OWNER`/`INFRA` actions.
