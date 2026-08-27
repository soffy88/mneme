# Mneme Production Launch Readiness Audit

Baseline: `ed6173a0ed7ab08aa414516ae54467db97cbf8f8`
Scope: first-user production launch engineering closure. This audit contains no production credentials, production data, deployment action, or real-user evidence.

## Status summary

| Area | Status | Evidence |
|---|---|---|
| Production Config | READY (code) / BLOCKED_OWNER | `services/production_config.py` rejects unsafe production settings; real secrets and approved origins are not present here. |
| Security | READY (code) | Safe config, upload boundaries, trace IDs, secret scan and existing sandbox/auth guards pass. |
| Auth | READY (API bearer contract) / BLOCKED_OWNER if cookie transport is selected | JWT expiry and server-side authorization are existing paths; cookie settings are fail-closed. |
| Data Isolation | READY | Existing IDOR protections and full suite pass; launch tests cover cross-user denial contracts. |
| Uploads | READY | Shared filename/content-type/size/path/cleanup boundary integrated into paper and textbook uploads. |
| Database | READY (code) / BLOCKED_INFRA | Alembic has one head, all migration files have downgrade functions, and preflight is read-only. Production current revision is not read. |
| Backup/Restore | BLOCKED_INFRA | Contract and `make restore-drill` are test-only; production backup, encryption, RPO/RTO and restore drill require infra. |
| Health | READY | `/health` is liveness only; `/readiness` checks critical DB/migration compatibility. |
| Degradation | READY | LLM/Redis/worker/storage/billing failure modes never fabricate learning evidence. |
| Idempotency | READY | Event uniqueness, policy decision lookup, pilot persistence and outcome projection uniqueness/idempotency are covered. |
| Workers | READY (code) / BLOCKED_INFRA | Late ack/time limits/signals are present; DLQ/alerts/worker capacity require infra. |
| Observability | READY (code) | Request errors/latency, event ingest, projection, policy fallback, dependency and worker counters are privacy-safe. |
| Privacy | READY (code) / BLOCKED_LEGAL | Purge/export boundaries and synthetic isolation pass; legal/privacy/guardian requirements need owner/legal decision. |
| Golden Paths | READY (test contract) | First-user, returning-user, failure and purge paths pass without real users; production smoke remains pending. |
| Early Access | READY (code) / BLOCKED_OWNER | Default closed and allowlist-controlled; owner must explicitly approve first users. |
| Operations | BLOCKED_OWNER/INFRA | Operator status is read-only and aggregate; on-call, alert routing, deploy/rollback and access review remain external. |
| Pilot | READY (engineering) / BLOCKED_OWNER/LEGAL/REAL_USERS | Existing pilot readiness passes; protocol approval, consent and observations are absent. |
| Product | READY (engineering) | Existing product readiness passes; no retention, learning effect or commercial claim is made. |

## Local evidence

- `git diff --check`: PASS.
- `./scripts/check.sh`: PASS — **1331 passed, 14 skipped, 110 warnings**, coverage **81.27%**; Ruff PASS; MyPy PASS (175 source files); test migration applied only to `mneme_test`.
- `make secret-scan`: PASS (tracked files; external secret stores not inspected).
- `make production-db-preflight`: PASS for unique head/downgrade inspection; `BLOCKED_OWNER` for current production revision because no production URL was supplied.
- `make pilot-readiness`: PASS — no real pilot result generated.
- `make product-readiness`: PASS — no real user, retention, revenue or learning-effect result generated.
- `make launch-readiness`: PASS — `LAUNCH ENGINEERING READY`, with owner/infra blockers printed.
- Frontend `npm ci`: PASS; `npm audit --audit-level=moderate`: 0 vulnerabilities; `npm run build`: PASS (12 application routes).

## Required external gates

- `OWNER`: provide production secrets, freeze approved config, approve early-access allowlist, deployment owner, support process and launch decision.
- `INFRA`: provision/verify production DB, migration execution, backups/restore, Redis, object storage, edge rate limits, monitoring and rollback.
- `LEGAL`: privacy/minor-data/guardian consent and pilot/research determination.
- `REAL_USERS`: first-user activation, D1/D7/D30 return, retention, independent learning outcomes and commercial evidence.

Current conclusion: **ENGINEERING COMPLETE** for the repository launch boundary; **SAFE TO DEPLOY AFTER OWNER/INFRA/LEGAL APPROVAL**; **REAL-WORLD EVIDENCE PENDING**.
