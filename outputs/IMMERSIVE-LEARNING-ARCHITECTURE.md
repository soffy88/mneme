# IMMERSIVE-LEARNING-ARCHITECTURE

> Product: **Mneme Immersive Learning**  
> Underlying engine: **Media Learning Engine** (language-agnostic)  
> First vertical: English  
> Design-only. Clean-room relative to DashPlayer (AGPL-3.0).  
> Must reuse Mneme LearningEvent → Evidence → CognitiveStateV2 → Policy → FSRS loop.

---

## 1. Goals

Give Mneme a native path:

```
Video / Audio
→ Transcript
→ Sentence / Segment Learning
→ Vocabulary / Grammar / Listening Evidence
→ LearningEvent
→ Evidence Graph
→ CognitiveState
→ Policy Engine
→ FSRS
→ Delayed Review
→ Transfer Evaluation
```

Not an English-only player. Supports: video, audio, podcast, course, lecture, language learning.

---

## 2. Module boundary

```
Immersive Learning
│
├── Media
├── Transcript
├── Segment
├── Language Scaffold
├── Practice
└── Mneme Core Integration
```

| Module | Responsibility | Must not |
|--------|----------------|----------|
| Media | Asset ingest, storage refs, playback session, continuity position | Own mastery / FSRS |
| Transcript | Sources, normalization, segmentation, provenance | Bind subtitle row as sole LearningUnit |
| Segment | Timed units for navigation/loop | Invent cognitive state |
| Language Scaffold | L0–L5 presentation; lookup UX | Encode `if replay>3 then quiz` |
| Practice | Listening/dictation/recall/transfer tasks | Self-judge mastery |
| Mneme Core Integration | Emit LearningEvents; call Evidence/Policy/Memory Router/FSRS | Duplicate schedulers |

Fits existing 3O + services layering: media/transcript workers as oprim/oskill; session orchestration in services; player in mneme-web.

---

## 3. Core domain model (design)

### 3.1 MediaAsset

| Field | Notes |
|-------|-------|
| id | UUID |
| owner | student_id / org_id |
| type | `video` \| `audio` |
| source_type | `LOCAL_UPLOAD` \| `OBJECT_STORAGE` \| `DIRECT_MEDIA_URL` \| `EXTERNAL_PROVIDER` |
| title | string |
| duration_ms | int |
| language | BCP-47 primary language |
| storage_ref | object storage key (nullable if external) |
| external_ref | provider id/url metadata (no DRM bypass) |
| content_provenance | `user_uploaded` \| `user_owned` \| `licensed` \| `public` \| `external_reference` |
| metadata | JSON (codec, size, checksum) |
| created_at | timestamptz |

### 3.2 Transcript

| Field | Notes |
|-------|-------|
| id | UUID |
| media_id | FK |
| source | `uploaded_subtitle` \| `embedded_subtitle` \| `manual` \| `asr` |
| format | `srt` \| `vtt` \| `json` |
| language | BCP-47 |
| model_version | ASR/MT model if generated |
| confidence | optional |
| provenance | source + timestamp + tool versions |
| created_at | timestamptz |

### 3.3 TranscriptSegment

| Field | Notes |
|-------|-------|
| segment_id | UUID |
| transcript_id | FK |
| start_ms / end_ms | inclusive window |
| text | source language |
| translated_text | optional |
| speaker | optional |
| language | |
| confidence | |
| order_index | |

**Forbidden:** treating subtitle row as the permanent sole LearningUnit identity.

### 3.4 LearningUnit

Polymorphic learning targets:

`segment` | `sentence` | `word` | `phrase` | `concept` | `grammar_pattern` | `listening_feature`

Identity is stable across media contexts (lemma/pattern ID), with **context links** to Media/Segment occurrences.

Example: `"You should've told me earlier."`

Links:

- LearningUnits: `should have`, past participle, `should've`, reduced speech, regret, spoken English
- Occurrence: Media A / Segment 42
- Later transfer: Media B / `"You should've called."`

### 3.5 MediaSession / Continuity

| Field | Notes |
|-------|-------|
| session_id | |
| student_id | |
| media_id | |
| position_ms | **playback continuity only** |
| current_segment_id | UX resume |
| scaffold_level | last applied / override |
| learning_state_refs | pointers to CognitiveState / due items — not embedded mastery |

**Boundary:** `position_ms` ∉ CognitiveState.

---

## 4. Media source strategy

| Adapter | V1 | Later | Notes |
|---------|----|-------|-------|
| LOCAL_UPLOAD | ✅ | | User uploads to object storage |
| OBJECT_STORAGE | ✅ | | Canonical serving via signed URL |
| DIRECT_MEDIA_URL | ⚪ limited | ✅ | Only if CORS/public + no DRM; no bypass |
| EXTERNAL_PROVIDER | ❌ | ✅ | YouTube/etc as **reference**, not downloader |

Hard rules:

- No DRM / paywall / platform restriction bypass
- Cognitive layer never imports a concrete provider SDK
- Content provenance always recorded

---

## 5. Transcript pipeline

```
media
→ transcript source
→ normalization
→ segmentation
→ language detection
→ sentence alignment
→ optional translation
→ learning-unit extraction (optional Phase 2)
```

Sources: uploaded subtitle, embedded subtitle, manual transcript, ASR-generated.

Every generated artifact records: `source`, `model/version`, `confidence`, `timestamp`.

Reuse existing: `vendor/oskill/knowledge/transcribe_audio_substrate.py` for ASR jobs (Phase 2).

---

## 6. Scaffold fading (L0–L5)

| Level | Presentation |
|-------|--------------|
| L0 | Bilingual subtitles |
| L1 | English subtitle only |
| L2 | Keyword hints |
| L3 | No subtitle |
| L4 | Active recall prompt |
| L5 | Delayed / transfer task |

- Policy Engine recommends level
- User may override
- Override → LearningEvent `SCAFFOLD_LEVEL_CHANGED` (behavioral), **not** ability evidence
- Player executes `PolicyDecision`; never embeds `if replay > 3 then quiz`

### Policy I/O

**Input:** CognitiveStateV2 (relevant LUs), EvidenceRefs, due FSRS, session scaffold history, uncertainty  
**Output:** recommended scaffold, pause-for-practice?, reveal translation?, generate review?, transfer test?, stop intervention  
**Trace:** existing `PolicyDecision` + reason_codes + evidence_refs

---

## 7. Player UX (independent design)

Workspace panes:

1. Video / Audio  
2. Transcript list  
3. Current Segment  
4. Learning Controls  

Controls: prev/next sentence, repeat, loop, play/pause, speed, subtitle toggle, translation toggle, word lookup, sentence explanation, bookmark, practice current sentence. Keyboard-first.

Transcript UX: follow playhead, click-to-seek, highlight current, search, sentence select, word interact; light status chips `new|learning|known|due` — avoid dashboard clutter.

---

## 8. Vocabulary learning

Flow: hover → click → lookup → save? → practice → review  

- First encounter: richer scaffold allowed  
- Later: CognitiveState-driven fading  
- **Forbidden:** lookup auto-creates FSRS item  
- Must pass **Memory Router eligibility policy**

Reuse: `vocabulary_items` + `vocab-{id}` knowledge_point convention (`services/vocab_service.py`).

---

## 9. Listening practice (V1+)

| Mode | Evidence |
|------|----------|
| Listen + understand | performance |
| Listen + choose meaning | performance |
| Listen + dictation | performance |
| Listen + fill blank | performance |
| Listen without subtitle | performance (stronger) |
| Listen with reduced scaffold | performance |

Results → LearningEvent RESULT → Evidence → Cognitive projection.

---

## 10. Pronunciation (interface only for V1)

```
audio response → ASR → pronunciation evaluator → confidence → Evidence
```

Low-confidence ASR must not become high-confidence mastery evidence. Full scoring deferred to Phase 2.

---

## 11. FSRS integration (single authority)

```
Video Evidence
→ eligibility (Memory Router)
→ FSRS item create/update OR evidence-only
```

| Case | Action |
|------|--------|
| Lookup only | Evidence only |
| First eligible performance miss on LU | May create FSRS item |
| Successful spaced recall / review | Update FSRS |
| Massed replay in same session | Evidence only; **do not** treat as spaced review |
| Contaminated (answer exposed / AI assisted without flags) | Evidence tagged; no mastery write |

Mneme FSRS remains scheduling authority (`vendor`/`oprim` fsrs path via existing cognitive write). No second scheduler.

**Memory Router (new named service boundary):**

Currently missing as an explicit component (FSRS updates today occur inside `process_interaction` / vocab path). Immersive Learning introduces an eligibility router that decides create / update / evidence-only / no-op without owning algorithm weights.

---

## 12. Cross-context review & transfer

Review of LU `wouldn't have` must not only replay Video A.

| Mode | Description |
|------|-------------|
| same-context recall | same media/segment |
| near-transfer | paraphrase / new numbers / sibling sentence |
| far-transfer | new media, new surface form, same pattern |

Reuse: `EvaluationPhase.near_transfer` / `far_transfer`, `transfer_probe_service`, `evaluation_os.transfer_metric`, CognitiveStateV2.transfer.

Transfer payload: source_context, target_context, distance, scaffold_level, result, confidence.

---

## 13. Learn Now integration

Learn Now continues to consume **server PolicyDecision** (`build_learn_now`).

New candidate action types (examples):

- `VIDEO_SEGMENT_TASK`
- `AUDIO_TASK`
- `DICTATION_TASK`
- `TRANSFER_TASK`
- `VOCAB_TASK`

No separate Video recommendation engine.

---

## 14. CognitiveState V2 language dimensions

Existing projection (`services/cognitive_state_v2.py`):

- knowledge (mastery_probability, confidence, evidence_count)
- memory (retrievability, stability, next_review_at, forgetting_risk)
- recognition
- transfer (near/far)
- misconception
- metacognition
- uncertainty
- provenance

### Extension strategy (no second learner state)

Express language facets as **knowledge_ref namespaces** + optional claim types:

| Dimension | Representation |
|-----------|----------------|
| Vocabulary | `vocab-{id}` mastery + memory |
| Phrase | `phrase-{id}` |
| Grammar pattern | `grammar-{id}` |
| Listening comprehension | `listening-{skill_id}` |
| Reduced / weak forms / connected speech | `listening_feature-{id}` |
| Pronunciation | `pron-{id}` (nullable until evidence) |
| Semantic comprehension | knowledge + recognition |
| Recall / Transfer | memory + transfer blocks |

**Minimal schema gap:** LearningUnit registry + occurrence edges + media tables. CognitiveStateV2 contract itself is extensible via `knowledge_ref` without a parallel state store. Optional later: typed sub-claims under `evidence_claims` for listening_feature breakdown — still projections.

Unsupported dims stay `null` (existing rule).

---

## 15. Knowledge / Evidence graph

```
Media → Segment → Sentence occurrence
                 → Vocabulary / Phrase / GrammarPattern / ListeningFeature / Concept
Attempt → Segment → LearningUnit → Evidence → CognitiveState
```

Existing: `MemoryEvidence`, `MemoryClaim`, `MemoryClaimEvidence`, `EvidenceRef`, `EvidenceClaim`.

Extend subject_type/claim_type vocabulary; add media occurrence edges. Do not invent a second graph product.

---

## 16. Privacy, purge, copyright

### Privacy classes

| Data | Class | Notes |
|------|-------|-------|
| Uploaded video/audio | P2–P3 | content + ownership |
| Transcript text | P2 | |
| Voice recording | P3 | |
| Lookup history | P2 | |
| Learning behavior events | P1–P2 | |

### Purge

New tables **must** join `_STUDENT_TABLES` in `services/purge_service.py` same PR.  
Object storage: extend textbook blob cleanup pattern (`storage_cleanup_pending` / `remove_object`) to media bucket.

### Copyright / provenance

`content_provenance` on MediaAsset + derived Transcript/Translation. Mneme does not circumvent DRM/paywalls.

---

## 17. Observability

Trace chain:

```
MediaSession → LearningEvent → Evidence → Cognitive projection
→ PolicyDecision → Memory Router → FSRS
```

Must answer:

- Why does Mneme believe the learner doesn't know this word?
- Why were subtitles hidden?
- Why is review scheduled tomorrow?

Reuse policy_trace, evidence explainers, projection checksums.

---

## 18. Data volume & performance

| Concern | Budget / approach |
|---------|-------------------|
| High-freq playhead | Telemetry sampling; never LearningEvent |
| 10k+ segments | Virtualized transcript list; segment window queries |
| Long video | Range requests / signed URL streaming |
| Seek latency | Client-side index of cues; O(log n) cue find |
| ASR jobs | Celery/worker async; never block player |
| Subtitle render | ≤1 frame delay target on cue change |

---

## 19. AI boundary

AI **may**: ASR, translation, explanation, example/exercise generation.  
AI **must not**: mastery authority, FSRS authority, policy authority.  
All AI output: versioned, traceable, confidence-aware (`EventProvenance`).

---

## 20. MVP (V1) vs Phase 2

### V1

- LOCAL_UPLOAD / OBJECT_STORAGE video  
- SRT/VTT transcript  
- Player + sentence nav + repeat + loop  
- EN/ZH subtitle toggles  
- Lookup + comprehension + dictation  
- LearningEvent taxonomy + Evidence + CognitiveState + Policy + FSRS + resume  

### Not V1

- YouTube downloader, complex multi-bitrate CDN, full pronunciation scoring, social, marketplace  

### Phase 2

- ASR / AI transcript, podcast/audio-only, pronunciation, auto LU extraction, cross-video transfer at scale, adaptive scaffold, external provider adapters  

---

## 21. ADR recommendations

| ADR | Decision sketch |
|-----|-----------------|
| Media Learning Engine | Language-agnostic engine under Immersive Learning product |
| Telemetry vs LearningEvent | Three-layer boundary; player telemetry ≠ evidence |
| Transcript Model | Segments ≠ LearningUnits; occurrences link LUs |
| LearningUnit Identity | Stable across contexts; media is context |
| Scaffold Policy | L0–L5 owned by Policy Engine; player executes |
| Media Evidence | Strength taxonomy; replay ≠ misunderstanding |
| FSRS Integration | Single scheduler; Memory Router eligibility |
| Content Provenance | Required on media + derived text |
| External Provider Boundary | No DRM bypass; cognitive layer provider-agnostic |

---

## 22. Architecture fit note

Mneme already has the product loop documented in `docs/PRODUCT_LOOP.md` and implemented via LearningEvent v2, Evidence Graph, CognitiveStateV2, PolicyDecision, Outcome Ledger, FSRS, Learn Now. Immersive Learning is a **new content/practice surface** feeding that loop — not a fork of it.
