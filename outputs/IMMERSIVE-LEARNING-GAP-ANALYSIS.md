# IMMERSIVE-LEARNING-GAP-ANALYSIS

> Architecture audit + gap matrix for integrating DashPlayer-class video language learning into Mneme.  
> Design-only. Code changed: **NO**.  
> DashPlayer license: **AGPL-3.0** → direct source reuse: **NO**.  
> Mneme RC2 baseline (user-stated): SHA `a48c14acf189a03de5eabb2ed0ea3ef4e4d4c725`, TAG `v0.1.0-rc2`, Migration head `5e7f8a9b0c12`.  
> Workspace note at audit time: HEAD was `966a9e9` (`v0.1.0-rc2-1-g966a9e9`); tags were not moved.

---

## 1. Mneme current capability matrix

Status legend: **CURRENT_CAPABILITY** · **REUSABLE** · **EXTEND** · **MISSING** · **CONFLICT**

| Area | Status | Code-backed finding |
|------|--------|---------------------|
| LearningEvent v2 | CURRENT + REUSABLE + EXTEND | `packages/event-schema` + `services/learning_event_service.py`; open `source`/`action`; idempotent append; no video taxonomy yet |
| Evidence / Evidence Graph | CURRENT + REUSABLE + EXTEND | `services/evidence_graph.py`, `MemoryEvidence`/`MemoryClaim`; needs media evidence types & strength policy |
| CognitiveState V2 | CURRENT + REUSABLE + EXTEND | `services/cognitive_state_v2.py`; knowledge/memory/recognition/transfer/metacognition/uncertainty; language dims via `knowledge_ref` namespaces |
| Learner Model / KC mastery write | CURRENT + REUSABLE | SubmitAnswer → cognitive path; vocab uses `vocab-{id}` via `vocab_service.py` |
| Memory Router (eligibility → FSRS) | MISSING (named) | FSRS updates embedded in process_interaction/vocab; no explicit media eligibility router |
| FSRS | CURRENT + REUSABLE | Single authority; must remain so |
| Policy Engine + Trace | CURRENT + REUSABLE + EXTEND | `mneme_core.policy_engine` + `policy_trace`; needs media candidates & scaffold actions |
| Outcome Ledger | CURRENT + REUSABLE | `LearningOutcomeLedger` / `PolicyOutcomeLink` |
| Transfer evaluation | CURRENT + EXTEND | `transfer_probe_service`, `evaluation_os`, `EvaluationPhase`; math-centric near-transfer today |
| Tutor / Agent | CURRENT | Chat/tutor loops; must not invent mastery |
| Content / Session / Learn Now | CURRENT + EXTEND | `product_closure.build_learn_now`; add VIDEO_* task types |
| Studio frontend | EXTERNAL | Real UI in `mneme-web` (out of this repo) |
| Storage / upload / OSS | CURRENT + EXTEND | MinIO `vendor/obase/oss.py`, `services/storage.py` textbook purge pattern |
| Worker / scheduler | CURRENT + EXTEND | Celery tasks; ASR/transcript jobs Phase 2 |
| Privacy / purge / export | CURRENT + EXTEND | `purge_service._STUDENT_TABLES`; new media tables + blob purge required |
| Observability | CURRENT + EXTEND | ingest metrics, policy traces, checksums |
| Media / transcript / player | MISSING (product) | Speaking + whisper substrate exist; no immersive player domain |
| English vocab bank | CURRENT + REUSABLE | `vocabulary_items` + FSRS KP convention |
| Speaking / STT | CURRENT + EXTEND | `speaking_sessions`, `_english_speaking_practice` — pronunciation interface precedent |
| CONFLICT | — | **Do not** create second event store, second CognitiveState, second FSRS, or player-local pedagogy ifs |

---

## 2. DashPlayer → Mneme concept reuse

| DashPlayer concept | Reuse mode |
|--------------------|------------|
| Sentence as study atom | INSPIRED_BY UX |
| Bilingual + hide/reveal | INSPIRED_BY scaffold |
| Prev/next/repeat/loop/speed | INSPIRED_BY controls |
| Hover vocab | INSPIRED_BY → eligibility-gated FSRS |
| AI sentence explain | INSPIRED_BY → AI boundary |
| Resume playhead | INSPIRED_BY continuity |
| Podcast mode | INSPIRED_BY Phase 2 |
| URL downloader / Electron / AGPL source | **Forbidden** |

---

## 3. Full gap matrix

Priority: **P0** architecture · **P1** MVP · **P2** enhancement · **P3** optional

| Capability | Mneme current | DashPlayer reference | Reuse | Extend | New | Schema | API | Frontend | Worker | Policy | Risk | Priority |
|------------|---------------|----------------------|-------|--------|-----|--------|-----|----------|--------|--------|------|----------|
| MediaAsset domain | none | local files | — | — | yes | yes | yes | upload UI | — | — | storage/privacy | P0 |
| Transcript + Segment | none / whisper substrate | SRT+ASR | substrate | yes | tables | yes | yes | transcript pane | ASR later | — | ASR cost | P0/P1 |
| LearningUnit identity | KC/vocab KP | subtitle≈unit | vocab KP | yes | LU registry | yes | yes | light status | extract later | yes | wrong identity | P0 |
| Player UX | none | full Electron player | concepts | — | web player | — | session API | **heavy** | — | executes decisions | UX quality | P1 |
| Sentence nav/repeat/loop | none | core UX | concepts | — | yes | — | events | yes | — | — | — | P1 |
| Bilingual scaffold L0–L5 | none | EN/ZH toggles | concepts | Policy | scaffold service | maybe | yes | toggles | — | **owns levels** | pedagogy leak | P0/P1 |
| Vocab lookup | vocab_service | hover dict | yes | eligibility | lookup events | — | yes | hover | — | eligibility | auto-FSRS risk | P1 |
| Listening/dictation | limited | manual practice | — | practice tasks | yes | items | yes | practice UI | — | schedule | scoring | P1 |
| Pronunciation | speaking path | TTS mostly | speaking | yes | interface | audio | yes | later | ASR | confidence caps | P2 |
| LearningEvent taxonomy | open strings | n/a | yes | video actions | ADR+tests | no breaking | ingest | emit | — | — | telemetry pollution | P0 |
| Evidence strength | levels exist | n/a | yes | media mapping | router rules | — | — | — | — | — | false mastery | P0 |
| Cognitive projection | V2 | n/a | yes | LU namespaces | — | minimal | read APIs | — | — | consumes | — | P0 |
| Memory Router | missing named | n/a | — | — | yes | — | internal | — | — | eligibility | double FSRS | P0 |
| FSRS | authority | none | yes | media items | — | no 2nd | — | — | — | — | schedule pollution | P0 |
| Transfer cross-video | math transfer | none | yes | media contexts | item gen | — | yes | tasks | — | transfer_need | sentence memorization | P1/P2 |
| Learn Now media tasks | product closure | n/a | yes | candidates | action types | — | yes | cards | — | rank | — | P1 |
| Continuity resume | none | watch_history | concepts | — | MediaSession | yes | yes | resume | — | ≠ cognition | confuse state | P1 |
| Privacy/purge media | textbook blobs | local-first claim | pattern | media blobs | tables in purge | yes | — | — | cleanup job | — | residual PII | P0 |
| Content provenance | partial | BYO media | — | — | fields | yes | yes | — | — | — | copyright | P0 |
| Observability chain | partial | n/a | yes | media traces | — | — | — | — | — | why?* | opacity | P1 |
| Telemetry plane | weak | dense player events | — | — | telemetry store/agg | maybe | — | client | — | — | event flood | P0 |
| External providers | none | download URL | — | — | adapters later | — | — | — | — | — | ToS/DRM | P3 |
| AI ASR/MT/explain | whisper/LLM paths | Whisper/Youdao/Tencent | patterns | yes | versioned outputs | — | yes | panels | jobs | never authority | AGPL temptation | P1/P2 |

---

## 4. Highest-risk architecture gaps

1. **Telemetry pollution** — player events flooding LearningEvent / FSRS  
2. **Subtitle-row-as-KC** — permanent binding prevents transfer  
3. **Lookup-local pedagogy** — `if replay>3` bypasses Policy Engine  
4. **Lookup-auto FSRS on lookup** — false memory items  
5. **AGPL copy temptation** — legal infection of network service  
6. **Object storage purge miss** — media residuals after user delete  
7. **Second learner state** — parallel “language profile” conflicting with CognitiveStateV2  

---

## 5. Highest-value capability

**Sentence-timed immersive practice that emits eligible performance Evidence into the existing CognitiveState → Policy → FSRS loop**, enabling delayed review and cross-context transfer of language LearningUnits — not a prettier player alone.

---

## 6. Schema impact

**YES** — new tables (at minimum): MediaAsset, Transcript, TranscriptSegment, LearningUnit (+ occurrence edges), MediaSession; possibly Telemetry aggregates; purge list updates; media object storage keys.

No change required to LearningEvent v2 envelope (open vocabulary). CognitiveStateV2 can extend via knowledge_ref namespaces without a parallel state table.

---

## 7. Scores (20-point scale)

| Dimension | CURRENT | MVP TARGET | FULL TARGET |
|-----------|---------|------------|-------------|
| Architecture Fit | 14 | 17 | 19 |
| Learning Science Fit | 12 | 16 | 19 |
| Mneme Core Reuse | 15 | 18 | 19 |
| Evidence Quality | 11 | 16 | 18 |
| Policy Integration | 13 | 17 | 19 |
| FSRS Integration | 14 | 17 | 19 |
| Transfer Capability | 10 | 14 | 18 |
| UX Potential | 6 | 14 | 18 |
| Implementation Complexity (higher=harder; invert for “good”) | 8 ease | 11 | 7 ease |
| License Safety | 18 (if clean-room held) | 18 | 18 |
| Privacy | 12 | 16 | 18 |
| Scalability | 11 | 14 | 17 |

**Composite architecture fit (primary):** CURRENT **14/20** → MVP **17/20** → Full **19/20**.

---

## 8. Reuse percentage (estimate)

| Bucket | Share of Immersive Learning effort |
|--------|--------------------------------------|
| Reuse as-is (Event/Evidence/State/Policy/FSRS/Learn Now/purge patterns) | ~45% |
| Extend | ~30% |
| New (media domain, player, taxonomy wiring, Memory Router, LU graph) | ~25% |

**Existing Mneme components reusable ≈ 55–65%** of the end-to-end capability surface (core loop heavy; player/media light).

---

## 9. Can implementation start without breaking RC2?

**YES** — feature branch + additive migrations after RC2; feature flags; no tag moves; no staging destructive ops; no AGPL vendoring.

Recommended: branch from current main **or** explicitly from `v0.1.0-rc2`, keep Immersive Learning behind flag until EPICs land.
