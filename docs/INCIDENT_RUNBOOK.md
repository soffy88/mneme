# Mneme Incident Runbook

This runbook is operational guidance, not permission to operate production. Preserve the trace ID and avoid copying private answers into tickets.

| Incident | Detection | Immediate action | Rollback / verification | Escalation |
|---|---|---|---|---|
| API down | health/readiness or request-error alert | stop rollout; inspect trace IDs and dependency status | roll back last release; verify `/health`, then `/readiness` | INFRA + OWNER |
| DB unavailable | `/readiness` database=false | keep writes stopped; do not run ad-hoc repair | restore approved backup in staging first; verify migration revision | INFRA |
| Redis unavailable | auth/worker/rate-limit errors | preserve durable LearningEvent path; disable non-critical queue work | recover Redis and replay only idempotent jobs | INFRA |
| LLM unavailable | provider failure metric | use deterministic learning core; show explanation unavailable | restore provider and run safe smoke tests | OWNER + INFRA |
| Worker backlog | worker failure/retry/poison counters | inspect bounded retries and isolate poison job | replay approved idempotent job after fix | INFRA |
| Migration failure | preflight or startup failure | do not retry blindly against production | use migration downgrade/runbook approved by owner; verify schema | INFRA + OWNER |
| Bad release | elevated 5xx or golden-path failure | disable launch/pilot flags; stop new enrollment | normal release rollback, then health/readiness/golden path | OWNER + INFRA |
| Privacy incident | privacy alert/report | preserve evidence, restrict access, stop exports | follow legal incident process and verify purge/export boundaries | OWNER + LEGAL |
| Suspected corruption | checksum/replay mismatch | freeze analysis/model promotion; preserve immutable events | rebuild projections from event cutoff in isolated environment | OWNER + INFRA |

Never fabricate a state or outcome to make an incident look healthy. Never execute production migration, restore, purge, or restart from this document without owner/infra approval.
