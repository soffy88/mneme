# Production Deployment Runbook

Provider-neutral sequence for an owner/infra-controlled deployment. The repository commands are safety checks; they do not deploy or migrate production.

1. Confirm owner approval, legal/privacy gates, real secrets, explicit origins, and `MNEME_ENV=production`.
2. Run `make secret-scan`, `make production-db-preflight`, and verify the production revision using an explicitly approved read-only channel.
3. Take and verify database and object-storage backups. RPO/RTO: `TBD_OWNER_DECISION`.
4. Apply Alembic migrations through the approved deployment mechanism; this repository command does not apply them to production.
5. Deploy the immutable application image with pilot, demo, notification, billing, and early-access flags off unless explicitly approved.
6. Verify `/health`, `/readiness`, worker status, logs, metrics, and frontend API configuration.
7. Run a non-sensitive smoke path and verify trace propagation. Do not use synthetic data in production analytics.
8. Monitor request errors, latency, DB availability, worker failures, event ingest/projection lag, LLM failures, upload failures and purge failures.
9. If verification fails, disable launch-specific flags and perform a normal rollback. Re-run readiness and smoke checks.

Production migration, backup restore, secret provisioning, external rate limiting, and deployment remain `OWNER`/`INFRA` actions.
