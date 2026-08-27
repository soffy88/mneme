# Mneme Staging Preflight

Run date: 2026-08-27 UTC
Release baseline: `ce8dc1a881152ef54e938685f68a63022169ebae`

## Result

`STAGING_DEPLOYMENT_BLOCKED_INFRA`

No separate production-like staging environment, staging credentials, staging database, staging object storage, staging Redis, staging worker/scheduler deployment, staging frontend origin, HTTPS endpoint, or staging telemetry destination was configured or supplied for this run. The local Docker Compose services are development/test infrastructure and were not relabeled as staging.

## Checks

| Check | Status | Evidence |
|---|---|---|
| Configuration with `ENVIRONMENT=staging` | BLOCKED_INFRA | No staging configuration source supplied |
| Database connectivity | BLOCKED_INFRA | No staging database endpoint supplied |
| Migration revision | BLOCKED_INFRA | No staging database may be touched |
| Redis | BLOCKED_INFRA | No staging Redis endpoint supplied |
| Object storage | BLOCKED_INFRA | No staging storage endpoint supplied |
| Worker | BLOCKED_INFRA | No staging worker deployment supplied |
| Scheduler | BLOCKED_INFRA | No staging scheduler deployment supplied |
| Frontend/backend connectivity | BLOCKED_INFRA | No staging frontend/backend endpoints supplied |
| `/health` | NOT_RUN | No staging endpoint |
| `/readiness` | NOT_RUN | No staging endpoint |

## Required staging configuration when infrastructure exists

- `ENVIRONMENT=staging`
- `DEBUG=false`, `DEMO_MODE=false`, `SYNTHETIC_ANALYTICS=false`
- no test database and no production secret reuse
- Pilot `OFF`
- Early Access `ON` only for owner-supplied test-account allowlist
- Notifications `OFF`
- Billing `OFF` / `NOT_CONFIGURED`

No staging deployment, migration, smoke test, failure injection, purge, or external service configuration was performed.
