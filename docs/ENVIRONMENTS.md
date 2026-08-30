# Mneme environment contract

This is the deployment identity contract. A hostname, reverse-proxy route,
container name, or image tag is not sufficient to identify production.

| Environment | `MNEME_ENV` | Purpose | Public exposure | DB / Redis / storage isolation | Allowed flags | Deployment source | Backup / retention | Release policy |
|---|---|---|---|---|---|---|---|---|
| development | `development` | Local engineering | None by default | Local disposable identities | Developer-controlled | Working tree | No backup; local retention | No release artifacts |
| test | `test` | Automated isolated tests | None | Disposable isolated identities | Test-controlled | CI/test commit | No backup; test retention only | No production data |
| demo | `demo` | Synthetic walkthroughs | Explicitly bounded | Demo-only identities | Demo-only; no production analytics | Demo-approved commit | Optional snapshot; bounded retention | Never production evidence |
| staging | `staging` | Release qualification | Internal-only | Dedicated staging identities | Canary/test flags allowed | Immutable candidate SHA | Restore-tested backup; staging retention | Qualified commit/artifacts only |
| production | `production` | Real learner service | Approved public routes | Explicitly named production identities | Global defaults fail closed; canary only by owner approval | Immutable approved release SHA | Current backup + restore metadata; policy retention | Approved release + owner gate |

`MNEME_ENV` is an enum, not a free-form label. Missing or unknown values fail
closed; `dev` and `prod` aliases are invalid. Every deployment must provide
the explicit value and resource identities above.

Production preflight requires explicit `DATABASE_URL`, `REDIS_URL`,
`MINIO_ENDPOINT`, `MINIO_BUCKET`, `GIT_SHA`, and `RELEASE_VERSION`, plus the
existing production secret/provider checks. Secret values are never emitted in
logs or audit documents. Production also requires a current PostgreSQL backup,
readable restore metadata, isolated Redis and object-storage identities, an
approved migration plan, and an exact immutable image digest.

Demo and staging credentials/resources must never be promoted or renamed as
production resources. Current repository evidence is contradictory: `CLAUDE.md`
describes the host as live production, while the checked-out runtime config is
`MNEME_ENV=demo` and the sxueji.com studio/MCP routes are documented as not yet
wired. Therefore `PRODUCTION_ENVIRONMENT_EXISTS=UNKNOWN` until an owner-backed
runtime/resource identity proves otherwise.

Immersive Learning defaults to `IMMERSIVE_LEARNING_ENABLED=false` and an empty
server-only `IMMERSIVE_LEARNING_CANARY_USER_IDS` list. The list is bounded,
UUID-validated, deduplicated, exact-match only, and never exposed to frontend,
API responses, or logs.
