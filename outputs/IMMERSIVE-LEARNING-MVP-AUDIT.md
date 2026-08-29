# IMMERSIVE-LEARNING-MVP-AUDIT

> Branch: `feat/immersive-learning-mvp`  
> Base: `a48c14acf189a03de5eabb2ed0ea3ef4e4d4c725` (`v0.1.0-rc2`)  
> Migration: `5e7f8a9b0c12` → `6a1b2c3d4e5f`  
> Date: 2026-08-29  
> License: clean-room; DashPlayer AGPL = INSPIRED_BY only

---

## Implemented architecture

Media Learning Engine under Immersive Learning product surface:

```
MediaAsset → Transcript → TranscriptSegment
                         → LearningUnitOccurrence → LearningUnit
MediaSession (continuity ≠ CognitiveState)
Telemetry plane (media_telemetry_events)
LearningEvent v2 (open vocabulary actions)
→ Evidence Graph → Memory Router → FSRS (single authority)
→ CognitiveStateV2 (knowledge_ref namespaces)
→ Policy Engine (scaffold + Learn Now candidates)
```

Feature flag: `IMMERSIVE_LEARNING_ENABLED` default **OFF** (fail-closed).

---

## Schema

Migration `6a1b2c3d4e5f_add_immersive_learning_tables.py`:

| Table | Purpose |
|-------|---------|
| media_assets | Video/audio ownership + storage_ref (not signed URL) |
| transcripts | PRIMARY / TRANSLATION subtitle docs |
| transcript_segments | Timed cues |
| learning_units | Stable cross-media identity `(kind, stable_key)` |
| learning_unit_occurrences | Segment context links |
| media_sessions | Playhead continuity |
| media_telemetry_events | High-frequency player telemetry |

ORM: `services/models.py` (`meta` attr maps DB `metadata`).

---

## APIs (`/v2/immersive`)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/status` | Flag probe |
| POST | `/{student_id}/media` | Upload mp4/webm/mp3/m4a/wav |
| GET | `/{student_id}/media` | List owned |
| GET | `/{student_id}/media/{id}` | Detail + short-lived playback URL |
| DELETE | `/{student_id}/media/{id}` | DB + blob |
| POST | `/{student_id}/media/{id}/transcript` | SRT/VTT |
| GET | `/{student_id}/media/{id}/segments` | Windowed list |
| POST | `/{student_id}/media/{id}/session` | Start/resume |
| PATCH | `/{student_id}/sessions/{id}` | Continuity |
| POST | `/{student_id}/telemetry` | Telemetry batch |
| POST | `/{student_id}/events` | LearningEvent ingest |
| POST | `/{student_id}/practice/*` | dictation/listening/comprehension/recall/transfer |
| POST | `/{student_id}/policy/recommend` | Scaffold + task recommendation |
| GET | `/{student_id}/learning-units/{stable_key}/occurrences` | Cross-media identity |
| POST | `/{student_id}/explain` | AI explain (degrades gracefully) |

All gated by flag except `/status`.

---

## Events

MVP LearningEvent actions (v2 envelope unchanged):  
`segment_replayed`, `subtitle_shown/hidden`, `translation_revealed`, `vocab_lookup`,  
`listening_*`, `dictation_*`, `comprehension_*`, `sentence_recall_*`, `scaffold_level_changed`,  
`transfer_*`.

Telemetry types stay off LearningEvent: `play|pause|seek|speed|segment_enter`.

---

## Evidence mapping / Memory Router

| Signal | Strength | FSRS |
|--------|----------|------|
| replay / lookup / translation reveal / scaffold override | weak behavioral | **never** |
| listening/dictation/comprehension/recall/transfer **result** | performance | eligible via Memory Router |

Actions: `NO_MEMORY_ACTION | CREATE_MEMORY | UPDATE_MEMORY | REVIEW_MEMORY`.

Duplicate `event_id`: `append_learning_event` → `inserted=False` → no second Evidence / cognition.

---

## Cognitive / FSRS / Policy

- No second learner state; LUs use `lu-{kind}-{stable_key}` knowledge_refs.
- FSRS only via existing `process_interaction` when Memory Router says advance.
- Policy recommends L0–L5 + Learn Now candidates (`VIDEO_SEGMENT_TASK`, `LISTENING_TASK`, …) when flag on.
- Player cannot compute intervals / hide-subtitle-from-mastery locally.

---

## Privacy / security

- New student tables in `purge_service._STUDENT_TABLES`.
- Media blob cleanup via `MEDIA_BUCKET=immersive-media`.
- `delete_media_asset` ownership-checked.
- Upload allowlist + filename sanitization + MIME check (not Content-Type alone).
- Subtitle HTML/script stripped.
- Cross-user: owned-media queries + `_ensure_student_self` / `require_student_access`.

---

## Frontend

`apps/mneme-studio/app/immersive` + components (clean-room).  
Keyboard-first controls; windowed transcript; practice panel; mock 10k mode.

---

## Tests

- `tests/test_immersive_learning_mvp.py`
- `tests/test_immersive_api_flag.py`
- `tests/test_immersive_security.py`
- `tests/test_immersive_merge_gate.py` (ML-07/13 MVP, telemetry contamination, policy L0–L5, no second scheduler)
- `apps/mneme-studio/e2e/immersive.spec.ts` (mock 10k + live-gated stub)
- hard_delete / upload_safety regression retained

---

## Performance

- Segment list API clamps `limit≤500` with offset windowing.
- Frontend TranscriptList windowed rendering for 10k cues (mock mode).
- **Browser validation (merge gate):** mock studio on isolated `:3102` with
  `NEXT_PUBLIC_IMMERSIVE_MOCK=1` — initial render ~710ms, **rendered DOM
  segment rows = 20** (<< 10_000), scroll kept row count < 500, seek + keyboard
  path exercised. Playwright mock test **PASS**.

---

## EPIC completion

| EPIC | Status |
|------|--------|
| ML-01 Domain Model | COMPLETE_FOR_MVP |
| ML-02 Media Storage | COMPLETE_FOR_MVP |
| ML-03 Transcript | COMPLETE_FOR_MVP |
| ML-04 Player | COMPLETE_FOR_MVP |
| ML-05 LearningEvent | COMPLETE_FOR_MVP |
| ML-06 Evidence | COMPLETE_FOR_MVP |
| ML-07 Cognitive Projection | COMPLETE_FOR_MVP (namespaces + deterministic projection; schema widen = Phase-2) |
| ML-08 Policy | COMPLETE_FOR_MVP |
| ML-09 FSRS / Memory Router | COMPLETE_FOR_MVP |
| ML-10 Practice | COMPLETE_FOR_MVP |
| ML-11 Transfer | COMPLETE_FOR_MVP (LU identity + transfer eligibility; fixture path) |
| ML-12 Privacy | COMPLETE_FOR_MVP |
| ML-13 Evaluation | COMPLETE_FOR_MVP (contamination/eligibility/transfer/scaffold evaluable; cohort dashboards = Phase-2) |
| ML-14 Observability | COMPLETE_FOR_MVP |
| ML-15 UX | COMPLETE_FOR_MVP |

No `MVP_REQUIRED_PARTIAL` remains. Phase-2 only: ASR, pronunciation, YouTube,
cohort dashboards, schema widen.

---

## Merge gate (2026-08-29)

### Release integrity

| Item | Value |
|------|-------|
| RC1_TAG_OBJECT_SHA | `82cc2cfd947acb7bb12bfb12d3e41c8ad9bfa862` |
| RC1_COMMIT_SHA | `a28edb25930232fb7af6150421d12a4237f655f2` |
| RC2_TAG_OBJECT_SHA | `917e97dd4050fc7d8bf54b28ddfc28eb1fd74db8` |
| RC2_COMMIT_SHA | `a48c14acf189a03de5eabb2ed0ea3ef4e4d4c725` |
| Merge-base(feat, rc2) | `a48c14a…` (= RC2 commit) |
| Tags moved? | NO |

Annotated tag object SHA ≠ peeled commit SHA (expected). Integrity **PASS**.

### Migration

- Old head: `5e7f8a9b0c12`
- New head: `6a1b2c3d4e5f` (single head)
- Clean `mneme_test` upgrade executed via `./scripts/check.sh`
- No old migration edits; downgrade present

### Gates executed

| Gate | Result | Notes |
|------|--------|-------|
| Full pytest (check.sh #1) | FAIL | 1375 passed, **3 failed**, 13 skipped, 927s; cov 78.41% ≥ 60% |
| Full pytest (check.sh #2) | FAIL | 1376 passed, **2 failed**, 13 skipped, 689s; cov 78.39% ≥ 60% |
| Coverage overall | PASS | 78.41% (fail_under 60) |
| Immersive core cov | LOW | router 49%, events 26%, media_service 17%, practice 26%, explain 0% — overall gate still PASS |
| Ruff full | PASS | |
| MyPy full | PASS | 187 files |
| Frontend typecheck | PASS | `tsc -p tsconfig.json --noEmit` + Next build TS |
| Frontend lint | N/A | no lint script in `package.json` |
| Frontend unit tests | N/A | no test script; Playwright separate |
| Frontend production build | PASS | |
| Playwright mock 10k | PASS | DOM rows=20; isolated `:3102` |
| Live Playwright golden path | **FAIL / not executed** | `IMMERSIVE_E2E_LIVE` stub only; no isolated non-prod API stack run |
| Cross-media live E2E | **FAIL / not executed** | unit LU identity only |
| Telemetry contamination | PASS | merge_gate unit |
| FSRS eligibility | PASS | merge_gate + mvp unit |
| Cognitive replay checksum | PASS | merge_gate unit |
| Scaffold policy L0–L5 | PASS | merge_gate unit |
| Privacy/purge inventory | PASS | hard_delete inventory includes immersive tables (in full suite) |
| Security hard matrix | **PARTIAL→FAIL for merge** | path/ext/timestamp/HTML strip covered; MIME spoof, IDOR, object-URL leak, unauthorized delete, oversized subtitle **not** fully live-exercised |
| Feature flag off | PASS | unit + status/404 |
| pilot/product/launch readiness | PASS | serial re-run after build lock cleared |
| scripts/check.sh #1 | FAIL | exit 1 — 3 pytest failures |
| scripts/check.sh #2 | FAIL | exit 1 — 2 pytest failures (`cli_whoami` timeout/env; `socratic_step_verify` arithmetic) |
| New skips/xfails vs RC2 | NONE in committed backend; E2E live path uses `test.skip` gate (expected) |

### 1st full-suite failures (environment / flake)

1. `test_cli_cannot_bypass_guard_cross_student_review_queue` — `httpx.ReadTimeout` to `localhost:8000` (prod API probe)
2. `test_memory_limit_actually_kills_over_limit_execution` — timing 2.54s > 2.0s (re-run PASS)
3. `test_svg_plot_produces_real_svg_from_kernel` — `success=False` (re-run PASS)

Not immersive regressions, but under Strict merge gate they still block `MERGE_READY=YES` until a clean full suite PASS.


### 2nd full-suite failures

1. `test_cli_whoami_against_real_running_server` — real `localhost:8000` probe flake
2. `test_pure_arithmetic_still_checked` — socratic step verify (non-immersive)

### MERGE_READY

**NO** — Strict policy: live isolated Playwright golden path not executed; full pytest not clean; security matrix incomplete.

Recommended next action: **FIX BLOCKERS** (isolated E2E stack + clean full suite + remaining security cases). Do **not** merge to main.

---

## Known limitations / Phase 2

- No ASR auto-transcript (upload SRT/VTT only)
- No YouTube/external provider adapters
- Pronunciation scoring interface deferred
- Explain sentence degrades without LLM provider
- Full DB E2E against live MinIO may need staging env with flag on
- Production/staging **not** deployed; flag remains off for RC2 behavior
- Live golden-path Playwright still stubbed behind `IMMERSIVE_E2E_LIVE=1`

---

## ADRs

See `docs/adr/ADR-IMMERSIVE-AGPL-BOUNDARY.md` and `0006`–`0015`.
