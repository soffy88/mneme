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
- `apps/mneme-studio/e2e/immersive.spec.ts`
- hard_delete / upload_safety regression retained

---

## Performance

- Segment list API clamps `limit≤500` with offset windowing.
- Frontend TranscriptList windowed rendering for 10k cues (mock mode).

---

## EPIC completion

| EPIC | Status |
|------|--------|
| ML-01 Domain Model | COMPLETE |
| ML-02 Media Storage | COMPLETE |
| ML-03 Transcript | COMPLETE |
| ML-04 Player | COMPLETE |
| ML-05 LearningEvent | COMPLETE |
| ML-06 Evidence | COMPLETE |
| ML-07 Cognitive Projection | PARTIAL (namespaces; no core schema widen) |
| ML-08 Policy | COMPLETE |
| ML-09 FSRS / Memory Router | COMPLETE |
| ML-10 Practice | COMPLETE |
| ML-11 Transfer | COMPLETE (fixture path + cross-media LU identity API) |
| ML-12 Privacy | COMPLETE |
| ML-13 Evaluation | PARTIAL (reuse existing evaluation_phase; no new cohort dashboards) |
| ML-14 Observability | COMPLETE (`immersive_requests_total` + traces on events) |
| ML-15 UX | COMPLETE |

---

## Known limitations / Phase 2

- No ASR auto-transcript (upload SRT/VTT only)
- No YouTube/external provider adapters
- Pronunciation scoring interface deferred
- Explain sentence degrades without LLM provider
- Full DB E2E against live MinIO may need staging env with flag on
- Production/staging **not** deployed; flag remains off for RC2 behavior

---

## ADRs

See `docs/adr/ADR-IMMERSIVE-AGPL-BOUNDARY.md` and `0006`–`0015`.
