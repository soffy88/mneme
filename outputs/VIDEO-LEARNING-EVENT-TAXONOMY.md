# VIDEO-LEARNING-EVENT-TAXONOMY

> Formal taxonomy for Immersive Learning / Media Learning Engine events.  
> Design-only. No implementation. No migration.  
> Must integrate with existing LearningEvent v2 (`packages/event-schema`), not a second event store.  
> Baseline: Mneme RC2 LearningEvent v2 (`source`/`action` are open strings governed by ADR + contract tests).

---

## 0. Three-layer event boundary (non-negotiable)

| Layer | Purpose | Enters CognitiveState? | Retention |
|-------|---------|------------------------|-----------|
| **Telemetry** | High-frequency player signals (timeupdate, buffer, UI chrome clicks) | No | Short (hours–days), sampled/aggregated |
| **LearningEvent** | Semantically meaningful learner actions / attempts | Maybe (via Evidence eligibility) | Long; purge with student |
| **Evidence** | Claims eligible for cognitive projection / FSRS | Yes (when eligible) | Long; purge with student |

**Rule:** Not every UI click is a LearningEvent. Not every LearningEvent is Evidence. Not every Evidence updates FSRS.

---

## 1. Envelope (maps onto LearningEvent v2)

All video learning facts use existing v2 fields:

| Field | Usage for media learning |
|-------|--------------------------|
| `source` | `immersive_player` \| `media_practice` \| `media_asr` \| `media_policy` |
| `action` | Taxonomy verb below |
| `object_type` | `media_asset` \| `transcript_segment` \| `learning_unit` \| `media_session` |
| `object_id` | Stable ID of the object |
| `knowledge_refs` | LearningUnit IDs / KC refs (e.g. `vocab-…`, `grammar-…`, `listening-…`) — **not** raw subtitle row IDs as permanent KCs |
| `item_features.modality` | `video` \| `audio` \| `transcript` |
| `item_features.format` | `listening` \| `dictation` \| `comprehension` \| `recall` \| `pronunciation` \| `scaffold` |
| `response` | Attempt payload |
| `outcome` | correctness / partial_credit / verifier / fsrs_rating (only when scored) |
| `process_signals` | latency, attempts, hints, active_learning_seconds |
| `intervention` | scaffold level, AI assist flags, policy decision id |
| `evaluation_phase` | practice / immediate_test / delayed_* / near_transfer / far_transfer / independent_no_ai |
| `provenance` | source system, model/version, confidence, content provenance |
| `privacy_class` | P0–P3 |
| `session_id` | MediaSession id |
| `trace_id` | End-to-end observability |

Idempotency: `event_id` unique + `event_checksum` conflict detection (existing `append_learning_event`).

---

## 2. Taxonomy catalog

Legend for columns:

- **Eligible evidence:** behavioral / performance / self-report / derived / none
- **Default strength:** weak / medium / strong (performance only can be strong)
- **Confidence:** suggested default; ASR/AI always capped
- **Privacy:** default class
- **Projection targets:** CognitiveState dimensions / Memory Router / Policy / none

### 2.1 Media lifecycle

#### MEDIA_STARTED

| Field | Definition |
|-------|------------|
| Semantic meaning | Learner began a MediaSession on an asset |
| Payload | `{media_id, position_ms, scaffold_level, transcript_id?}` |
| Eligible evidence | behavioral (session start only) |
| Confidence | 1.0 |
| Idempotency | `(student, session_id, MEDIA_STARTED)` once |
| Privacy | P1 |
| Retention | student lifetime / purge |
| Projection | Policy context only; **not** mastery |

#### MEDIA_PAUSED

| Field | Definition |
|-------|------------|
| Semantic meaning | Explicit pause (not buffer stall) |
| Payload | `{media_id, position_ms, segment_id?, reason?}` |
| Eligible evidence | none by default → prefer Telemetry |
| Confidence | n/a |
| Idempotency | allow many; optional debounce |
| Privacy | P1 |
| Retention | short if telemetry; else session |
| Projection | none |

#### MEDIA_SEEKED

| Field | Definition |
|-------|------------|
| Semantic meaning | Explicit seek to a new position |
| Payload | `{from_ms, to_ms, method: scrub\|cue_click\|keyboard}` |
| Eligible evidence | none by default (telemetry) |
| Confidence | n/a |
| Idempotency | high-frequency → telemetry aggregation |
| Privacy | P1 |
| Retention | short |
| Projection | none |

#### MEDIA_COMPLETED

| Field | Definition |
|-------|------------|
| Semantic meaning | Reached end / marked complete for session |
| Payload | `{media_id, watched_ratio, active_learning_seconds}` |
| Eligible evidence | weak behavioral |
| Confidence | 0.5 |
| Idempotency | once per session |
| Privacy | P1 |
| Projection | Policy (return/continue); not mastery |

---

### 2.2 Segment interaction

#### SEGMENT_ENTERED

| Field | Definition |
|-------|------------|
| Semantic meaning | Playhead entered a TranscriptSegment (debounced) |
| Payload | `{segment_id, start_ms, end_ms, media_id}` |
| Eligible evidence | none (telemetry) unless aggregated |
| Confidence | n/a |
| Idempotency | debounce ≥ cue duration / 2 |
| Privacy | P1 |
| Projection | none |

#### SEGMENT_REPLAYED

| Field | Definition |
|-------|------------|
| Semantic meaning | Learner intentionally replayed a segment once |
| Payload | `{segment_id, replay_count_session, method}` |
| Eligible evidence | **weak behavioral** |
| Confidence | 0.3 |
| Idempotency | count via aggregation key |
| Privacy | P1 |
| Projection | Policy scaffold hint only — **never** `did_not_understand=true` |

#### SEGMENT_LOOPED

| Field | Definition |
|-------|------------|
| Semantic meaning | A–B loop active over one or more segments |
| Payload | `{from_segment_id, to_segment_id, loop_count}` |
| Eligible evidence | weak behavioral |
| Confidence | 0.3 |
| Idempotency | start/stop events; count aggregated |
| Privacy | P1 |
| Projection | Policy only |

---

### 2.3 Scaffold / subtitle controls

#### SUBTITLE_SHOWN / SUBTITLE_HIDDEN

| Field | Definition |
|-------|------------|
| Semantic meaning | Subtitle visibility changed (EN track) |
| Payload | `{track: source\|translation\|both\|none, scaffold_level}` |
| Eligible evidence | behavioral (manual override) |
| Confidence | 0.2 |
| Privacy | P1 |
| Projection | Policy override log; **not** ability evidence |

#### TRANSLATION_REVEALED

| Field | Definition |
|-------|------------|
| Semantic meaning | Translation track revealed for current segment |
| Payload | `{segment_id, previous_level, new_level, trigger: user\|policy}` |
| Eligible evidence | behavioral if user; intervention if policy |
| Confidence | 0.2 |
| Privacy | P1 |
| Projection | Metacognition help-seeking signal (weak); not vocabulary mastery |

#### SCAFFOLD_LEVEL_CHANGED

| Field | Definition |
|-------|------------|
| Semantic meaning | Scaffold level L0–L5 changed |
| Payload | `{from, to, actor: user\|policy, decision_id?}` |
| Eligible evidence | behavioral (user) / intervention (policy) |
| Confidence | 1.0 for fact of change |
| Privacy | P1 |
| Projection | Policy trace; **manual override ≠ competence** |

---

### 2.4 Lookup / help (not automatic FSRS)

#### VOCAB_LOOKUP

| Field | Definition |
|-------|------------|
| Semantic meaning | Learner looked up a word/token in context |
| Payload | `{token, lemma?, segment_id, learning_unit_id?, surface_form, context_span}` |
| Eligible evidence | weak behavioral / self-report-ish |
| Confidence | 0.4 |
| Privacy | P2 (content + behavior) |
| Projection | Memory Router eligibility candidate **only**; **must not** auto-create FSRS item |

#### PHRASE_LOOKUP

| Field | Definition |
|-------|------------|
| Semantic meaning | Multi-word / idiom lookup |
| Payload | `{phrase, segment_id, learning_unit_id?}` |
| Eligible evidence | weak behavioral |
| Confidence | 0.4 |
| Privacy | P2 |
| Projection | same as vocab |

#### GRAMMAR_HELP_REQUESTED / EXPLANATION_REQUESTED

| Field | Definition |
|-------|------------|
| Semantic meaning | Asked for grammar or sentence explanation |
| Payload | `{segment_id, learning_unit_ids[], ai_model?, prompt_version?}` |
| Eligible evidence | weak behavioral + intervention |
| Confidence | 0.3 |
| Privacy | P2 |
| Projection | Metacognition help_seeking; AI output versioned, not mastery |

---

### 2.5 Performance attempts (stronger evidence)

#### LISTENING_ATTEMPT / LISTENING_RESULT

| Field | Definition |
|-------|------------|
| Semantic meaning | Listening comprehension check (with/without subtitle) |
| Payload attempt | `{task_id, segment_ids[], scaffold_level, item_format}` |
| Payload result | `{correctness, partial_credit, choices?, verifier, verifier_version}` |
| Eligible evidence | **performance** |
| Confidence | 0.8–0.95 if deterministic verifier; lower if LLM-graded |
| Privacy | P1–P2 |
| Projection | Cognitive knowledge/recognition; Memory Router may advance FSRS if eligible |
| evaluation_phase | practice or immediate_test |

#### DICTATION_ATTEMPT / DICTATION_RESULT

| Field | Definition |
|-------|------------|
| Semantic meaning | Write-what-you-hear for segment/sentence |
| Payload result | `{expected, submitted, edit_distance, correctness, partial_credit}` |
| Eligible evidence | **performance** (strong for listening+orthography) |
| Confidence | 0.85+ with deterministic scorer |
| Privacy | P2 |
| Projection | listening + recall learning units |

#### COMPREHENSION_ATTEMPT / COMPREHENSION_RESULT

| Field | Definition |
|-------|------------|
| Semantic meaning | Meaning check (MCQ / short answer) |
| Eligible evidence | performance |
| Confidence | depends on verifier |
| Privacy | P1–P2 |
| Projection | semantic comprehension LU |

#### SENTENCE_RECALL_ATTEMPT / SENTENCE_RECALL_RESULT

| Field | Definition |
|-------|------------|
| Semantic meaning | Active recall of sentence/pattern without full audio scaffold |
| Eligible evidence | performance |
| evaluation_phase | practice / delayed_test |
| Projection | recall LU; FSRS eligible when policy says so |

#### PRONUNCIATION_ATTEMPT / PRONUNCIATION_RESULT

| Field | Definition |
|-------|------------|
| Semantic meaning | Spoken production scored by ASR/evaluator |
| Payload | `{audio_ref, asr_text, score, confidence, evaluator_version}` |
| Eligible evidence | performance **capped by ASR confidence** |
| Confidence | min(evaluator, ASR confidence); **never treat low-ASR as strong mastery** |
| Privacy | **P3** (voice) |
| Projection | pronunciation dimension; V1 may record interface only |

#### TRANSFER_ATTEMPT / TRANSFER_RESULT

| Field | Definition |
|-------|------------|
| Semantic meaning | Same LearningUnit tested in different media/context |
| Payload | `{source_context, target_context, distance: same\|near\|far, scaffold_level}` |
| Eligible evidence | **performance** |
| evaluation_phase | near_transfer / far_transfer / independent_no_ai |
| Confidence | 0.9 with deterministic items |
| Privacy | P1–P2 |
| Projection | CognitiveState.transfer; Outcome Ledger |

---

## 3. Evidence strength policy

| Signal | Strength | May imply |
|--------|----------|-----------|
| Replay ×4 | weak behavioral | possible difficulty — **not** `did_not_understand=true` |
| Translation revealed | weak behavioral | scaffold dependency — not vocabulary unknown |
| Vocab lookup | weak | candidate for richer scaffold next time |
| No-subtitle listening incorrect | **strong performance** | listening LU weakness |
| Dictation incorrect | **strong performance** | listening/orthography gap |
| Transfer correct across videos | **strong performance** | pattern learning, not sentence memorization |
| Low-confidence ASR pronunciation | capped ≤0.4 | store but do not drive mastery |

Derived evidence (aggregates) must be separately versioned and never silently promoted to performance.

---

## 4. Telemetry vs LearningEvent routing

| Player signal | Route |
|---------------|-------|
| `timeupdate` / buffering / volume | Telemetry only |
| play/pause spam < 1s | Telemetry |
| seek scrubbing | Telemetry aggregate |
| intentional sentence repeat | LearningEvent `SEGMENT_REPLAYED` |
| loop range set | LearningEvent `SEGMENT_LOOPED` |
| lookup / practice / transfer | LearningEvent |
| policy decision applied | LearningEvent + PolicyDecision link |

Aggregation examples: replay_count per segment per session; seek_histogram per media.

---

## 5. Privacy classes for media events

| Class | Examples |
|-------|----------|
| P0 | anonymized aggregates |
| P1 | media_id, segment_id, scaffold level, correctness |
| P2 | transcript text snippets, lookup tokens, dictation text |
| P3 | uploaded media ownership metadata? voice recordings, raw audio responses |

Export/redaction: P2/P3 redacted by default in parent/process exports (existing Evidence Model).

---

## 6. Contract tests required (design)

1. Duplicate `event_id` → no double Evidence / no double FSRS update  
2. Replay same evidence set → identical CognitiveState projection checksum  
3. `VOCAB_LOOKUP` alone → Memory Router returns `no_fsrs_item`  
4. Manual scaffold override → PolicyTrace records override; CognitiveState mastery unchanged  
5. `PRONUNCIATION_RESULT` with ASR confidence < 0.5 → evidence strength capped  
6. Telemetry volume stress: 10k timeupdates → zero LearningEvent pollution  

---

## 7. Mapping cheat-sheet to LearningEvent v2 actions

Recommended `action` strings (open vocabulary; ADR-governed):

```
media_started, media_paused, media_seeked, media_completed,
segment_entered, segment_replayed, segment_looped,
subtitle_shown, subtitle_hidden, translation_revealed, scaffold_level_changed,
vocab_lookup, phrase_lookup, grammar_help_requested, explanation_requested,
listening_attempt, listening_result,
dictation_attempt, dictation_result,
comprehension_attempt, comprehension_result,
sentence_recall_attempt, sentence_recall_result,
pronunciation_attempt, pronunciation_result,
transfer_attempt, transfer_result
```

`source` values: `immersive_player`, `media_practice`, `media_worker`, `learn_now`.
