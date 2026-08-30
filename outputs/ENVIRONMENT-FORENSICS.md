# Environment forensics — v0.1.0-rc4

Date: 2026-08-30 UTC
Scope: read-only repository, local runtime metadata, deployment documents,
reverse-proxy evidence, and isolated staging metadata. Secrets and learner
content were not read or recorded.

## Identity evidence

- Starting `main` SHA: `9a9d0f76aff067844daa9b70a98a53aa9118080a`.
- The checked-out local runtime reports `MNEME_ENV=demo`; its local Compose
  resource identities are demo-shaped (`mneme` database/bucket and Redis DB
  `0`). This is recorded as an observed identity, not promoted to production.
- Compose files, `.env*` references, deployment scripts, systemd/proxy
  references, CI workflows, README/release docs, and the sxueji deployment
  runbook were inspected without emitting secret values.
- The repository contract requires explicit production DB, Redis, object
  storage, release SHA/version, backup, and owner evidence. No independent
  owner-backed production resource identity was found locally.
- The isolated RC4 staging stack uses separate local Compose resources and
  synthetic test principals only. Demo resources and credentials were not
  copied or renamed.

## Route map

| Public route | Intended proxy/service | Evidence status |
|---|---|---|
| `sxueji.com/studio/*` | `mneme-studio:3001` | Deployment documentation only; public wiring not proven locally |
| `sxueji.com/mcp/*` | Mneme API MCP router | Deployment documentation only; public wiring not proven locally |
| `api.sxueji.com` | Mneme API | Health response observed, but exact environment/resource identity not proven |
| `prod.*`, `production.*`, `staging.*` | Candidate environment routes | No owner-backed local route contract found |

The route documents and the observed demo runtime do not prove that the
public host is a separately provisioned production environment. Hostname-only
classification is intentionally rejected.

## Data/environment map

| Candidate runtime | DB identity | Redis identity | Storage identity | Artifact identity |
|---|---|---|---|---|
| Observed local runtime | `mneme` (demo-shaped) | DB `0` (demo-shaped) | `mneme` (demo-shaped) | existing non-RC4 local image; not release proof |
| RC4 isolated staging | dedicated Compose Postgres service | dedicated Compose Redis service | dedicated Compose MinIO service | API/worker/beat/frontend all carry RC4 SHA `a359877676a39fc2627a6f429adea77b0ed41311` |
| Production candidate | not established | not established | not established | not established |

No user counts, LearningEvent counts, or learning content were queried.

## Outcome

`CURRENT_PUBLIC_RUNTIME_CLASSIFICATION=UNKNOWN`
`OBSERVED_LOCAL_RUNTIME_IDENTITY=DEMO`
`PRODUCTION_ENVIRONMENT_EXISTS=UNKNOWN`

Production identity remains a post-RC4 infrastructure discovery/provisioning
gate. RC4 qualification evaluates only the immutable candidate artifacts and
isolated staging behavior; no production deployment was attempted.
