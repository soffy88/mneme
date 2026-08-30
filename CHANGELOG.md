# CHANGELOG

All notable changes to Mneme are documented in this file. This project does
**not** follow SemVer in the strict sense — the leading `0.1.x` line is a
pre-1.0 release train. Pre-release versions are tagged as `v0.1.0-rcN`.

## v0.1.0-rc3 — Immersive Learning MVP

**Release date**: 2026-08-30
**Source feature SHA**: `05377c9b09b7815c8f3ba0362f4619827a08bfb3`
**Staging runtime SHA**: `0b8bf9f96c8cbb3f9d51e83027f9b9f948f7041e`
**Code release SHA**: `b5d41c32e4ffe52e2ed41902c7345598b8a5549b`
**Release metadata commit**: `SELF_TAGGED_COMMIT`
**Alembic head**: `7b2c3d4e5f6a`
**Feature flag**: `IMMERSIVE_LEARNING_ENABLED` (default **OFF**, opt-in per env)

This release adds the **Immersive Learning MVP** to Mneme: a video-grounded
learning surface where a student watches a media asset, follows a sentence
navigator, and practices the four production capabilities — dictation,
listening paraphrase, multiple-choice comprehension, and sentence recall.
The MVP is a **Phase-1** delivery: the immersive workspace is feature-flagged
behind `IMMERSIVE_LEARNING_ENABLED=true` and is not enabled by default in
production.

### What ships

**Domain primitives**

- `MediaAsset` — uploaded audio/video media; provenance (`USER_UPLOADED`),
  `processing_state` (READY/...), language, duration, MIME type
- `Transcript` + `TranscriptSegment` — SRT/VTT ingestion, primary role,
  sentence-level timestamps, text + translated text, speaker
- `MediaSession` — per-asset continuity state: playhead_ms, current segment,
  scaffold_level (0–5), state machine (`ACTIVE` / `PAUSED` / `ENDED`)
- `MediaTelemetryEvent` — interaction plane only (play/pause/seek/seek_to/...).
  **Does not** create Evidence. Telemetry is continuity, not cognition.
- `LearningEvent v2` integration with `evidence_strength` (`performance` for
  explicit practice, `behavioral` for telemetry-derived signals)
- `Evidence` integration: dictation / listening / comprehension / recall
  events route through `MemoryRouter` → `kc_mastery` via the same pipeline
  that already powers paper and book practice
- `CognitiveStateV2` integration: every practice result returns
  `cognition.p_mastery`, `cognition.long_term_mastery`,
  `cognition.next_review_due`, `cognition.rating`
- `Policy/v2` integration: per-segment policy decisions with reason codes
  (`RECOMMEND_SCAFFOLD_LEVEL`, `WHY_SUBTITLE_VISIBLE_LOW_EVIDENCE`, etc.)

**Practice surfaces** (under `IMMERSIVE_LEARNING_ENABLED`)

- **Listening** — paraphrase the segment's meaning; deterministic
  verifier (`immersive.listening_normalize` v1.0.0)
- **Dictation** — type the segment text; edit-distance scoring
  (`immersive.dictation_normalize` / `dictation-score/1.0.0`); partial credit;
  normalized text comparison
- **Comprehension** — multiple choice over a segment-bound question;
  placeholder `question_provenance.source=studio_mvp_placeholder` for now
  (real question bank is Phase-2)
- **Sentence recall** — free recall of the segment text
- **Cross-media transfer** — exercise a knowledge unit on a second media
  asset; the `TransferRequest` schema forces explicit
  `source_media_id/source_segment_id/target_media_id/target_segment_id/
  knowledge_ref` so a partner can never silently link to a wrong asset

**FSRS, scaffold, and continuity**

- L0–L5 scaffold levels (L0 = full visibility, L5 = no scaffolding); per-
  segment scaffolding decisions are recorded in `MediaSession.scaffold_level`
- FSRS (`/v1/students/{id}/mastery`) is the **only** writer of `kc_mastery`
  `p_mastery`. No agent, partner, or CLI can self-judge mastery; the partner
  self-test `tests/test_partner_no_self_judged_mastery.py` enforces this at
  AST level
- Sentence navigator and playhead are continuity primitives — they do not
  write CognitiveState (the API explicitly annotates this in
  `POST /v2/immersive/{user}/media/{id}/session` with
  `note: "playhead is continuity only; not CognitiveState"`)

**Security & isolation**

- All `/v2/immersive/{student_id}/...` routes enforce
  `_ensure_student_self` / `_ensure_student_access` (see
  `services/auth_deps.py`). Cross-user reads return 404, cross-user session
  PATCH returns 404
- `media_id`, `segment_id`, `session_id` are all UUIDs; Pydantic validation
  rejects path traversal, XSS, and oversized payloads with 422 (no
  traceback, no SQL escaping layer involved)
- Unauth access to any immersive route → 401
- Partner self-test (no agent, no CLI can write mastery directly) is enforced

**Privacy & purge**

- `services/purge_service._STUDENT_TABLES` includes the new tables
  (`media_assets`, `media_sessions`, `media_telemetry_events`,
  `transcripts`, `transcript_segments`, `memory_evidence` for the
  immersive path). Hard-delete a student → immersive data is also
  purged in the same transaction
- No PII (real student media) is shipped in this manifest; only the
  synthetic fixture phone numbers `13900099001–13900099004` are present
  in the staging qualification audit and are documented as
  `IMMERSIVE_STAGING_TEST_USER_*`

**Feature flag (hard gate)**

- `IMMERSIVE_LEARNING_ENABLED` defaults to **OFF**
- `services/feature_flags.py::_explicitly_on` requires the env value to
  parse as one of `1`/`true`/`yes`/`on`; otherwise the route group
  returns 404 (the existing routes are hidden, not auth-rejected, so
  external clients cannot probe their existence)
- `GET /v2/immersive/status` is **always** reachable and reports
  `{enabled: <bool>}` without leaking the disabled routes' shapes

**Migrations (additive only — rollback-safe)**

- `6a1b2c3d4e5f_add_immersive_learning_tables` — CREATE TABLE for
  `media_assets`, `transcripts`, `transcript_segments`, `media_sessions`,
  `media_telemetry_events`, with appropriate indexes and FKs
- `7b2c3d4e5f6a_add_immersive_interaction_source` — adds
  `InteractionSource.IMMERSIVE` enum value
- **Both** migrations are CREATE-only; downgrade to `5e7f8a9b0c12` simply
  orphans the new tables (no FK coupling back into the core path)
- Single alembic head confirmed: `7b2c3d4e5f6a`

**Frontend**

- `/studio/immersive` route added under `apps/mneme-studio`; renders the
  ImmersiveWorkspace (left: video player, right: transcript + practice
  panel, top: PlayerControls). Server-rendered shell with client-side
  hydration; production build emits a static page for `/studio/immersive`
- Existing routes (`/`, `/login`, `/library`, etc.) unaffected

**MCP tools**

- All immersive capabilities are exposed via the existing
  `/mcp/*` route surface (see `services/mcp_router.py`). No new
  MCP surface was added; immersive is a feature flag, not a tool
  taxonomy change

### What does NOT ship in this MVP (deferred to Phase 2)

The following capabilities are **explicitly out of scope** for v0.1.0-rc3
and must not be marketed or implied:

- **ASR** — there is no automatic speech recognition. SRT/VTT must be
  uploaded alongside the media. The media service stores the audio but
  does not transcribe
- **Pronunciation scoring** — listening is paraphrase, not pronunciation.
  Audio waveforms are stored; spoken-recording comparison is Phase 2
- **Full production LLM explain provider** — `POST /v2/immersive/{user}/explain`
  returns `status: "degraded"` when no LLM provider is configured
  (staging uses `MNEME_LLM=mock`); the player remains usable
- **External media provider integrations** — YouTube / Vimeo / Bilibili
  fetch, podcast RSS expansion, channel import — all Phase 2
- **Question bank with provenance** — comprehension currently accepts a
  placeholder `question_provenance.source=studio_mvp_placeholder`; a
  real curated question bank with grade-specific scaffolding is Phase 2
- **Full production rollout** — `IMMERSIVE_LEARNING_ENABLED` is OFF in
  production. The flag is staged ON in `mneme-staging` only as part of
  qualification

### What changed under the hood (silent)

- `services/immersive/` — new module, isolated; does not import from
  `services/main.py` outside the optional route registration gated on
  `immersive_learning_enabled()`
- `services/routers/immersive.py` — new router; mounted only when flag
  is on
- `packages/event-schema` — `LearningEvent v2` accepts
  `evidence_strength=performance|behavioral`
- `vendor/oskill/memory_router.py` — accepts `media_id` as an
  additional provenance anchor; does not write to `kc_mastery` for
  `evidence_strength=behavioral` events from pure telemetry
- `services/feature_flags.py` — adds `IMMERSIVE_LEARNING_ENABLED` constant
  and helper, default OFF
- `alembic/versions/6a1b2c3d4e5f_…` and `7b2c3d4e5f6a_…` — new
  additive migrations

### Upgrade path from v0.1.0-rc2

- `git fetch && git checkout v0.1.0-rc3`
- `alembic upgrade head` (rolls forward `5e7f8a9b0c12 → 7b2c3d4e5f6a`,
  additive only)
- Set `IMMERSIVE_LEARNING_ENABLED=true` in any environment where
  immersive should be available (default: off)
- The flag is off by default; the existing RC2 user-visible surface
  (paper/book/corner/studio/library) is unchanged

### Verification

- Full `scripts/check.sh` passes against the release commit
  (1386 tests, 0 failures, coverage 80%+)
- Frontend typecheck + production build pass; `/studio/immersive` route
  emitted as static page
- Staging qualification: 56/56 functional assertions + 30/30 soak samples
  clean (see `outputs/IMMERSIVE-STAGING-QUALIFICATION.md`,
  `outputs/IMMERSIVE-STAGING-SOAK.json`)
- Targeted immersive suite (LearningEvent, Evidence, CognitiveState,
  Policy, FSRS, privacy/purge, security, feature flag) all PASS
- Static secret scan: clean (no production secrets, no test-phone
  PII leaked into runtime artifacts)
- Dependency security: no new CRITICAL/HIGH CVEs

### Known limitations (carried forward, not blockers)

- `evidence_strength=performance` is the only path that advances FSRS in
  the immersive path. Telemetry-only events do not (correctly) advance
  mastery — this is by design (see §3.4 of the Immersive Learning
  Architecture document)
- The placeholder comprehension question provenance is an interim
  contract; a real question bank will replace it in Phase 2
- The staging soak ran 30 minutes; longer (8h+) soak is required before
  production canary

---

## v0.1.0-rc2 — earlier pre-release

See `outputs/RELEASE-MANIFEST-v0.1.0-rc1.md` and the rc1/rc2 manifests
in `outputs/`. Both rc1 (`a28edb25…`) and rc2 (`a48c14ac…`) are
**unchanged** by this release.

## v0.1.0-rc1 — earlier pre-release

`a28edb25930232fb7af6150421d12a4237f655f2`, unchanged.
