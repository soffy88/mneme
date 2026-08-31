# Production provisioning — v0.1.0-rc4

Date: 2026-08-30 to 2026-08-31 UTC
Status: internal production infrastructure provisioned; no public routing and no
user rollout.

This record contains resource identities and verification results only. It does
not contain credentials, tokens, learner content, or real-user identifiers.

## Outcome

`PRODUCTION_ENVIRONMENT_EXISTS=YES` for the independently provisioned internal
production stack. The existing public/demo-shaped runtime was not renamed or
reused. `PRODUCTION_PUBLICLY_EXPOSED=NO` and `PUBLIC_ROUTE_STATUS=OWNER_BLOCKED`.

The production identity is now explicit internally; the remaining public-route
and live-provider actions are separate rollout/owner gates.

## Environment and resource identity

Source contract: `docs/ENVIRONMENTS.md`. Prior discovery:
`outputs/ENVIRONMENT-FORENSICS.md`.

| Resource | Production identity | Existing demo/staging boundary |
|---|---|---|
| Environment | `MNEME_ENV=production` | Demo remains `demo`; staging remains `staging` |
| Compose project | `mneme-production` | Demo project/resources remain `mneme-*`; staging project is `mneme-staging` |
| Networks | `mneme-production-internal`, `mneme-production-edge` | Staging uses `mneme-staging-internal`, `mneme-staging-edge`; demo uses existing `helios-net`/`mneme_default` memberships |
| PostgreSQL | service `mneme-production-db-1`, database `mneme_production`, user `mneme_prod`, volume `mneme-production-pg-data` | Staging database/service/volume are independently named; demo database is the existing demo-shaped `mneme` resource |
| Redis | service `mneme-production-redis-1`, isolated instance DB 0, namespace `mneme-production`, volume `mneme-production-redis-data` | Staging has a separate Redis service/volume; demo Redis was not touched |
| Object storage | MinIO service `mneme-production-minio-1`, bucket `mneme-production`, prefix `production/`, volume `mneme-production-minio-data` | Staging bucket/service/volume remain separate; demo bucket/resources were not touched |
| Services | API, worker, beat, frontend, edge all have `mneme-production-*` names | Existing demo and staging services were not recreated or repointed |
| Internal route | loopback `127.0.0.1:18081` → production edge → production API/frontend | No existing public route was changed |

Production has no bind-mounted source checkout. API, worker, beat, and frontend
run the immutable RC4 image tags below.

## RC4 artifact identity

- `CODE_RELEASE_SHA`: `a359877676a39fc2627a6f429adea77b0ed41311`
- Release: `v0.1.0-rc4`
- RC4 annotated tag object: `e146ca52a4c5107e817a63beed25aad9b4eb8c9d`
- RC4 peeled commit: `70cb423ee536f8a8312d40aa19b98a40dd39e363`
- Release metadata commit: `70cb423ee536f8a8312d40aa19b98a40dd39e363`

| Service | Image tag | Digest | Runtime SHA proof |
|---|---|---|---|
| API | `mneme-api:v0.1.0-rc4-a359877676a3` | `sha256:32aec19baf11a7523398fa6b013d09ee65c83c548f732709d430f7dd90007c33` | OCI revision label and `GIT_SHA` match `a359877676a39fc2627a6f429adea77b0ed41311` |
| worker | `mneme-worker:v0.1.0-rc4-a359877676a3` | `sha256:32aec19baf11a7523398fa6b013d09ee65c83c548f732709d430f7dd90007c33` | OCI revision label and `GIT_SHA` match the code release SHA |
| beat | `mneme-beat:v0.1.0-rc4-a359877676a3` | `sha256:32aec19baf11a7523398fa6b013d09ee65c83c548f732709d430f7dd90007c33` | OCI revision label and `GIT_SHA` match the code release SHA |
| frontend | `mneme-web:v0.1.0-rc4-a359877676a3` | `sha256:aefdde6da5a7580ff596dfffa9849f2d66c9705d1c37a8a00e17958628d73495` | OCI revision label and `GIT_SHA` match the code release SHA |

All four services report release `v0.1.0-rc4`; no image was rebuilt for
production provisioning.

## Migration and initial data

- New production DB began empty: no Alembic revision and no learner rows.
- `alembic upgrade head` completed successfully.
- Final revision: `7b2c3d4e5f6a`.
- `alembic heads`: one head, `7b2c3d4e5f6a`.
- Initial production data contains schema/bootstrap data and one synthetic
  isolation marker account created solely for infrastructure verification.
- No demo/staging user rows, LearningEvent content, or learner content were
  copied. `PRODUCTION_DATA_CONTAINS_REAL_USERS=NO`.

## Backup and restore

Backup: `prod-20260830T225808Z`
Retention: 30 days
Backup root: `/data/soffy/mneme-production/backups/prod-20260830T225808Z`

The backup includes a PostgreSQL custom-format dump, object-storage manifest and
objects, the production compose/edge configuration, and the RC4 release
manifest. Secrets remain external in the mode-600 production config and are not
included in the backup.

An isolated restore rehearsal passed:

- PostgreSQL dump restored into a temporary isolated database.
- Restored schema revision was `7b2c3d4e5f6a`, single head.
- Restored synthetic marker was verified without reading learner content.
- Object-storage marker and manifest restored and verified in an isolated
  temporary MinIO instance.
- Temporary restore resources were removed after verification.

## Fail-closed identity and isolation proof

Production preflight passed with the explicit production environment, DB,
Redis, storage, code SHA, and release version. Negative tests rejected wrong or
missing DB, Redis, storage, `MNEME_ENV`, and `GIT_SHA`; the environment matrix
accepted only `development`, `test`, `demo`, `staging`, and `production`, and
rejected missing/invalid values and `dev`/`prod` aliases.

The production marker was visible only in production:

- Production DB marker count: 1; demo DB count: 0; staging DB count: 0.
- Production Redis marker: present; demo and staging Redis marker: absent.
- Production object marker: present; demo and staging object marker: absent.
- A known staging synthetic principal was absent from production.
- Production and staging networks and named volumes are distinct.
- No demo/staging write, restart, recreate, deletion, credential copy, or route
  modification was performed.

## Global-off smoke and observability

Final production config:

- `IMMERSIVE_LEARNING_ENABLED=OFF`
- `IMMERSIVE_LEARNING_CANARY_USER_IDS=EMPTY`
- No real user is in a canary list.

Through the internal production route, core auth/bootstrap, LearningEvent,
CognitiveState, Policy, FSRS queue, Learn Now, Today, Memory, and Progress
smoke checks passed. Authenticated immersive status is disabled and unauthenticated
immersive requests are denied; no immersive route was enabled for a production
user.

Observability checks passed:

- `/health`, `/readiness`, `/health/metrics`, `/health/providers`, and
  `/health/grading` responded as expected.
- Metrics expose aggregate counters, including the gate decision series, with
  no user ID, email, phone, password, secret, or token fields.
- No production secret value appeared in the sampled API, worker, beat, or edge
  logs.
- Production config root is mode 700, secrets directory mode 700, and the
  external `.env.production` file mode 600.
- Container restart count was zero at final verification.

The provider status endpoint reports the default/mock LLM/VLM fallback because
no live provider credential was activated in this no-rollout environment. The
production preflight still rejects explicit mock mode (`MNEME_ALLOW_MOCK_LLM=1`)
and mock auth; live provider activation is a required owner action before any
real-user canary or formal rollout.

## Rollback rehearsal

An isolated recovery rehearsal redeployed the exact RC4 fallback digest without
database downgrade. Health and readiness returned 200 before and after the
redeploy, and the schema remained at `7b2c3d4e5f6a`. A deliberately attempted
older RC3 fallback was rejected by its own sandbox self-check and did not touch
production; it was not used as the passing rollback result.

## Internal soak

Configuration remained global immersive OFF with an empty allowlist for the full
window:

- Window: `2026-08-30T23:15:42Z` – `2026-08-30T23:46:15Z`
- Samples: 30
- API 5xx: 0
- Edge 5xx: 0
- DB errors: 0
- Worker errors: 0
- Projection errors: 0
- FSRS errors: 0
- API/worker/beat/frontend/edge restarts: 0
- All health, readiness, frontend, DB, Redis, and storage samples passed.

## Public routing and rollout status

The existing route evidence remains owner-controlled and contradictory across
historical runbooks: `sxueji.com/studio`, `sxueji.com/mcp`, and
`api.sxueji.com` were not proven to map to this newly provisioned production
stack. No Cloudflare/DNS/aegis route was changed, and the existing demo route
was not covered or replaced.

A final read-only probe observed `sxueji.com/studio/learn` HTTP 200,
`sxueji.com/mcp/health` HTTP 404, and `api.sxueji.com/health` HTTP 200. These
status codes do not establish environment identity and do not show the new
loopback-only production edge as their backend.

Therefore:

- `PUBLIC_ROUTE_STATUS=OWNER_BLOCKED`
- `EXISTING_DEMO_ROUTES_MODIFIED=NO`
- `PRODUCTION_CODE_DEPLOYED_INTERNALLY=YES`
- `PRODUCTION_PUBLICLY_EXPOSED=NO`
- `FORMAL_USER_ROLLOUT=NO`
- `INTERNAL_PRODUCTION_READY=YES` for isolated infrastructure and RC4
  artifact deployment; live provider activation and owner-approved public
  routing remain rollout gates.
- `PRODUCTION_PROVISIONED=YES`

## Qualification summary

- P0 blockers: NONE.
- P1 rollout blockers: `ROUTING_OWNER_BLOCKER`; live LLM/VLM provider
  activation is also required before real-user rollout.
- RC4 tag unchanged: YES.
- RC1/RC2/RC3 tags unchanged: YES.
- Production immersive global flag: OFF.
- Production canary allowlist: EMPTY.

Next gate: `PUBLIC ROUTING` after owner approval and live-provider readiness;
then a separately authorized `PRODUCTION CANARY`. This provisioning record does
not authorize GA or formal user rollout.
