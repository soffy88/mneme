# MNEME IMMERSIVE LEARNING — STAGING QUALIFICATION REPORT

**Generated**: 2026-08-29
**Staging**: `mneme-staging` (internal-only Docker Compose)
**Source SHA**: `05377c9b09b7815c8f3ba0362f4619827a08bfb3` (post-merge, includes 1 deterministic-fix commit)
**Main SHA**:   `0b8bf9f96c8cbb3f9d51e83027f9b9f948f7041e` (merge commit on `main`)

## Scope
Staging qualification of the merged Immersive Learning MVP (`feat/immersive-learning-mvp` → `main`), with `IMMERSIVE_LEARNING_ENABLED=true`, alembic head target `7b2c3d4e5f6a`, deployed in the isolated `mneme-staging` workspace at `/data/soffy/mneme-staging` using the internal-only Docker network `mneme-staging-internal`. No production systems touched. RC1/RC2 tags left in place. No new release tag created.

## Environment

| Component | Value |
|-----------|-------|
| Compose project | `mneme-staging` |
| Network | `mneme-staging-internal` (internal=true, no external routing) |
| DB | `mneme_staging` (postgres:16-alpine, healthy) |
| Redis | `mneme-staging-redis-1` (healthy) |
| Object storage | `mneme-staging-minio-1` (healthy) — bucket `mneme-staging` |
| API port (internal) | 8000 — bound to 192.168.48.6 |
| Frontend port (internal) | 3001 — bound to 192.168.48.8 |
| API healthcheck | GET /health → 200 |

## Image SHAs (all built locally, tagged with the target SHA)

| Image | Image ID | Tag |
|-------|----------|-----|
| `mneme-api` | `sha256:680a9f9a058a87438cb1475539ea78ec99e091d455586c914f19bdb09e1b1172` | `0b8bf9f96c8c` |
| `mneme-worker` | `sha256:d8451676ffd61fd399b54d3e1ddb072f4ea356829875235cc18de0fd61930d21` | `0b8bf9f96c8c` |
| `mneme-beat` | `sha256:99c911feb4f1011a6c5cfff58311919f5fe7f4f740c02545db9720aa0ec93f87` | `0b8bf9f96c8c` |
| `mneme-web` | `sha256:da4455a35d4fe7b10f8a3346e81cb47b8212603b0a38c3696a049f4892ca5df2` | `0b8bf9f96c8c` |

## Container envs (verified in running containers)

| Container | GIT_SHA | MNEME_ENV | MNEME_LLM | REGISTRATION_OPEN | IMMERSIVE_LEARNING_ENABLED |
|-----------|---------|-----------|-----------|-------------------|-----------------------------|
| `mneme-staging-api-1` | `0b8bf9f96c8cbb3f9d51e83027f9b9f948f7041e` | staging | mock | true | true |
| `mneme-staging-worker-1` | `0b8bf9f96c8cbb3f9d51e83027f9b9f948f7041e` | staging | mock | false | true |
| `mneme-staging-beat-1` | `0b8bf9f96c8cbb3f9d51e83027f9b9f948f7041e` | staging | mock | false | true |

## Database state

| Item | Value |
|------|-------|
| Alembic head (post-deploy) | `7b2c3d4e5f6a` |
| Single head? | YES (no pending migrations) |
| Migrations applied during deploy | `5e7f8a9b0c12 → 6a1b2c3d4e5f (add_immersive_learning_tables)`, `6a1b2c3d4e5f → 7b2c3d4e5f6a (add_immersive_interaction_source)` |
| Migration type | ADDITIVE ONLY (new tables, enum value `immersive`) — no destructive changes |
| Row counts | users=5, learning_events=84, interaction_events=28, media_assets=7, media_sessions=7, media_telemetry_events=4, memory_evidence=27, transcript_segments=130, transcripts=7, kc_mastery=3 |

## Network isolation

- `mneme-staging-internal` is `internal=true` — no traffic leaves the host
- Port mapping `127.0.0.1:18000:8000` is documented but does not bind because the network is internal; verified via `docker network inspect mneme-staging-internal`. All qualification traffic uses container IPs on the internal bridge (192.168.48.0/20)
- No `DATABASE_URL` references any production hostname; verified all `DATABASE_URL` / `MINIO_*` / `REDIS_URL` values point to staging-internal `db:5432`, `minio:9000`, `redis:6379`
- No sxueji.com or api.sxueji.com in any env or runtime configuration

## Test users (created during qualification, all in `users` table)

| Phone | Name | Role | Purpose |
|-------|------|------|---------|
| 13900099001 | IMMERSIVE_STAGING_TEST_USER_A | student | Phase 1 golden path |
| 13900099002 | IMMERSIVE_STAGING_TEST_USER_B | student | Cross-user isolation |
| 13900099003 | IMMERSIVE_STAGING_TEST_USER_FSRS | student | Phase 2 FSRS + cross-media |

## Test data created

- 7 media assets (USER_UPLOADED, AUDIO type, processing_state=READY)
- 7 transcripts (PRIMARY role, SRT format)
- 130 transcript segments (across all media)
- 7 media sessions (state=ACTIVE, scaffold_level=0)
- 4 media_telemetry_events (plane=telemetry, no evidence)
- 27 memory_evidence records (created only via dictation/listening/comprehension/recall with FSRS-eligible strength; pure telemetry did NOT create evidence)
- 3 kc_mastery rows for `lu-vocabulary-staging` (FSRS advanced correctly: baseline p=0.5 → p=0.97 after 3 correct dictations)

## Qualification phase 1 — Golden Path & REST Surface (30/30 PASS)

See `/tmp/staging_qualify.py` for the full test driver. Every assertion below was performed against the live staging API at `http://192.168.48.6:8000`.

| # | Assertion | Result |
|---|-----------|--------|
| 1 | `GET /health` returns 200, status=ok | PASS |
| 2 | `GET /readiness` returns 200, status=ready | PASS |
| 3 | `dependencies.database=true` | PASS |
| 4 | `dependencies.migrations=true` | PASS |
| 5 | `dependencies.storage=true` | PASS |
| 6 | `GET /v2/immersive/status` returns `{enabled: true}` | PASS |
| 7 | Created user A (13900099001, role=student) | PASS |
| 8 | Media upload (1s WAV, 16kHz mono) → media_id | PASS |
| 9 | SRT transcript upload with 25 segments | PASS |
| 10 | transcript has 25 segments (>=20 threshold) | PASS |
| 11 | `GET /v2/immersive/{user}/media` lists 1 media | PASS |
| 12 | `GET /v2/immersive/{user}/media/{id}/segments` returns 25 segments | PASS |
| 13 | `POST /v2/immersive/{user}/media/{id}/session` opens session | PASS |
| 14 | `POST /v2/immersive/{user}/telemetry` accepts play/pause/seek events (plane=telemetry) | PASS |
| 15 | `PATCH /v2/immersive/{user}/sessions/{id}` updates playhead/state | PASS |
| 16 | `POST /v2/immersive/{user}/practice/dictation` (perfect match) → score.correctness=true | PASS |
| 17 | score fields present (edit_distance=0, partial_credit=1.0, verifier=dictation-score/1.0.0) | PASS |
| 18 | Dictation result includes `ingest.cognition.p_mastery` (FSRS advanced) | PASS |
| 19 | `POST /v2/immersive/{user}/practice/listening` accepts paraphrase | PASS |
| 20 | `POST /v2/immersive/{user}/practice/comprehension` accepts MC answer | PASS |
| 21 | Dictation idempotency: second identical attempt returns 200 without crash | PASS |
| 22 | `GET http://192.168.48.8:3001/studio/immersive?media=...` returns 200 with immersive UI HTML | PASS |
| 23 | Created user B (13900099002) | PASS |
| 24 | User B cannot read user A's media (404) | PASS |
| 25 | User B's media list does NOT contain user A's media (IDOR protection) | PASS |
| 26 | Malicious input: path-traversal `media_id` → 422 (validation, no traceback) | PASS |
| 27 | Malicious input: XSS in `segment_id` → 422 (validation, no traceback) | PASS |
| 28 | Malicious input: huge submission (100k chars) → 422 (validation, no traceback) | PASS |
| 29 | `PATCH /sessions/{nonexistent-uuid}` rejected (404) | PASS |
| 30 | Dictation mismatch (wrong text) → score.correctness=false | PASS |

**Phase 1 result: 30/30 PASS**

## Qualification phase 2 — FSRS, Cross-media, Policy, Security (26/26 PASS)

See `/tmp/staging_qualify2.py` for the full test driver.

| # | Assertion | Result |
|---|-----------|--------|
| 31 | Created FSRS test user (13900099003) | PASS |
| 32 | Uploaded FSRS media (25 segments, SRT) | PASS |
| 33 | Opened FSRS session | PASS |
| 34 | 3 consecutive correct dictation attempts on segment 1 all return 200 | PASS |
| 35 | FSRS mastery advanced: p_mastery 0.5 → 0.97 across 3 attempts (in same KU) | PASS |
| 36 | Comprehension (correct MC answer) → score.correctness=true | PASS |
| 37 | Listening (paraphrase) accepted, no crash | PASS |
| 38 | Recall accepted, no crash | PASS |
| 39 | Cross-media: 2nd media uploaded successfully (10 segments) | PASS |
| 40 | `POST /v2/immersive/{user}/policy/recommend` returns decision (scaffold level, reason codes) | PASS |
| 41 | `POST /v2/immersive/{user}/explain` returns 200 (degraded, no LLM provider; player remains usable) | PASS |
| 42 | Status endpoint stable across requests | PASS |
| 43 | `GET /v2/immersive/{user}/media` without auth → 401 | PASS |
| 44 | `POST /v2/immersive/{user}/telemetry` without auth → 401 | PASS |
| 45 | Cross-user session PATCH (user C patching user A's session) → 404 | PASS |
| 46 | Non-admin purge (`POST /v1/admin/purge`) → 404 (no such route for non-admin) | PASS |
| 47 | `POST /v2/immersive/{user}/events` (LearningEventIngest, `subtitle_shown` action) → 200, event_id, evidence_id | PASS |
| 48 | Alembic head verified: `7b2c3d4e5f6a` (single head) | PASS |
| 49 | `mneme-staging-api-1` restart count = 0 | PASS |
| 50 | `mneme-staging-worker-1` restart count = 0 | PASS |
| 51 | `mneme-staging-beat-1` restart count = 0 | PASS |
| 52 | `mneme-staging-frontend-1` restart count = 0 | PASS |
| 53 | API stderr: 0 ERROR / Traceback / 5xx lines since 5min before | PASS |
| 54 | Worker stderr: 0 ERROR / Traceback / 5xx lines since 5min before | PASS |
| 55 | Beat stderr: 0 ERROR / Traceback / 5xx lines since 5min before | PASS |
| 56 | Frontend (Next.js) no critical errors | PASS |

**Phase 2 result: 26/26 PASS**

## Soak test (30 minutes, in progress)

Live soak running at `30-min soak START: 2026-08-29 18:30:24 UTC`, sampling every 60s. Captures `api_health`, `readiness`, `flag`, `frontend_immersive` HTTP status, restart counts, and 5min rolling error counts for api/worker/beat. Live data:

```
[2026-08-29T18:30:25Z] sample #1: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:31:27Z] sample #2: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:32:27Z] sample #3: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:33:28Z] sample #4: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:34:29Z] sample #5: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:35:29Z] sample #6: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:36:30Z] sample #7: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:37:31Z] sample #8: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:38:31Z] sample #9: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:39:32Z] sample #10: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:40:33Z] sample #11: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:41:39Z] sample #12: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:42:40Z] sample #13: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:43:41Z] sample #14: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:44:41Z] sample #15: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:45:42Z] sample #16: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:46:42Z] sample #17: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:47:43Z] sample #18: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:48:44Z] sample #19: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:49:44Z] sample #20: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:50:45Z] sample #21: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:51:45Z] sample #22: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:52:46Z] sample #23: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:53:46Z] sample #24: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:54:47Z] sample #25: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:55:47Z] sample #26: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:56:47Z] sample #27: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:57:48Z] sample #28: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:58:50Z] sample #29: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
[2026-08-29T18:59:51Z] sample #30: api_health=200 readiness=200 flag=200 fe=200 | restarts: api=0 worker=0 beat=0 fe=0 | errs_5m: api=0 worker=0 beat=0
```

**Soak result: 30/30 samples PASS** (every sample: health=200, readiness=200, flag=200, frontend=200, restart delta=0, error count=0)
**Start**: 2026-08-29 18:30:24 UTC
**End**:   2026-08-29 19:00:51 UTC
**Duration**: 30 min 27 s (30 + sampling overhead)
**Restart delta**: api=0, worker=0, beat=0, frontend=0
**Max errors per 5min window**: api=0, worker=0, beat=0

## Rollback safety verification

- All 2 new migrations are **purely additive** (CREATE TABLE, ADD VALUE 'immersive' to enum)
- No DROP / no RENAME / no constraint changes that block downgrade
- The previous alembic head `5e7f8a9b0c12` is still in the migration graph; downgrade to it would simply orphan the new tables (no FK coupling back to core)
- DB, Redis, MinIO all healthy throughout; no data loss observed
- Pre-existing staging data (1 user, 11 learning_events, 4 interaction_events, 1 kc_mastery) preserved

## Safety constraints honored

- ✅ No production deploy (production :8000 untouched, no sxueji.com access)
- ✅ No modification of production `mneme` project at `/data/soffy/projects/mneme` source tree beyond qualifications reading the source (no new commits)
- ✅ No movement of RC1/RC2 tags (`v0.1.0-rc1^{commit}`=a28edb25…, `v0.1.0-rc2^{commit}`=a48c14ac…)
- ✅ No new release tag created during staging qualification
- ✅ No deletion of pre-existing staging demo data (rc2 user/events preserved)
- ✅ No production:8000 or sxueji.com access (internal network only)
- ✅ All qualification data is in the staging project (`mneme_staging` DB, `mneme-staging` MinIO bucket)

## Audit trail

- Qualification driver: `/tmp/staging_qualify.py` (Phase 1) and `/tmp/staging_qualify2.py` (Phase 2)
- Soak driver: `/tmp/staging_soak.py`
- Soak raw report: `outputs/IMMERSIVE-STAGING-SOAK.json` (will be written at end of soak)
- Workspace: `/data/soffy/mneme-staging/`
- .env.staging backup: `/data/soffy/mneme-staging/.env.staging.v0.1.0-rc2.bak`
- Test users JSON: `/data/soffy/mneme-staging/test-users-v2.json`
