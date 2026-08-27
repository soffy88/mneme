# Mneme Production Gap Audit

Baseline: `ed6173a0ed7ab08aa414516ae54467db97cbf8f8`
Audit scope: first-user launch closure. No production database, deployment, secret, or external service was accessed.

| Area | Status | Evidence / remaining action |
|---|---|---|
| Configuration validation | READY | `services/production_config.py`; production rejects debug/demo/fake auth/billing/test DB/default secrets/wildcard CORS. Owner must supply real values. |
| Secret safety | READY | `make secret-scan`; tracked-file scan passes. External secret manager still requires owner/infra setup. |
| Database schema/migrations | READY | Single Alembic head and downgrade functions; `make production-db-preflight` is read-only. Current production revision requires infra access. |
| Database backup/restore | NEEDS_INFRA | Contract and non-production drill command exist; backup storage, RPO/RTO, and restore authority are deployment responsibilities. |
| Redis | NEEDS_INFRA | Existing auth/Celery Redis usage is bounded; production HA, persistence, and alerting require infra. |
| Object storage | NEEDS_INFRA | Upload boundary and purge cleanup are code-covered; production bucket policy, encryption, and lifecycle require infra. |
| Authentication/session | READY | Server-side bearer authorization and expiry remain the canonical API contract; deleted users invalidate access. Cookie contract is fail-closed if enabled. |
| CSRF/CORS | NEEDS_OWNER | Bearer API is not cookie-authenticated; any browser cookie transport must use the validated Secure/HttpOnly/SameSite contract and explicit origins. |
| Rate limiting | NEEDS_INFRA | Central budgets are declared in `services/abuse_controls.py`; distributed enforcement belongs at Redis/edge deployment. |
| Uploads | READY | Filename traversal, content type, size cap, partial-file cleanup and private ownership are covered at both upload routes. |
| Background jobs | READY | Celery late-ack, time limits, retry/failure signals and worker health counters are present. DLQ retention/alerting requires infra. |
| Health/readiness | READY | `/health` is liveness; `/readiness` checks DB and migration compatibility. |
| Graceful degradation | READY | Dependency degradation contract never fabricates evidence; deterministic core remains the source of truth. |
| Error UX | READY | Unhandled errors return a safe message and trace ID; server logs retain only error type/trace ID at this boundary. |
| Privacy/purge | READY | New launch records remain student-scoped and purge inventory is existing single source; no new PII fields were added. |
| Early access | READY | `EARLY_ACCESS_MODE` is off and allowlist is empty by default; owner must explicitly open it. |
| Operator surface | READY | Admin-only `/v2/operator/status` is aggregate/read-only and excludes private answers. |
| Frontend API/build | READY | Existing Studio build remains the frontend contract; production API URL/configuration must be supplied by owner/infra. |

## Non-code blockers

- `OWNER`: production secrets, approved origins, session transport, early-access allowlist, launch checklist and legal/consent approval.
- `INFRA`: production database revision, backups/restore drill, Redis/object-storage reliability, rate limiting, deployment and monitoring.
- `LEGAL`: terms, privacy notice, K-12/minor consent and pilot/research determination.
- `REAL_USERS`: first-user activation, retention, learning outcomes and commercial evidence do not exist in this repository and are not claimed.
