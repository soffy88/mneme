# IMMERSIVE-LEARNING-IMPLEMENTATION-PLAN

> Executable EPIC plan for Mneme Immersive Learning / Media Learning Engine.  
> Design-only this round — **do not implement yet**.  
> Clean-room vs DashPlayer. Additive to RC2. Feature-flagged.

---

## 0. Guardrails

- No AGPL source/port  
- No second FSRS / CognitiveState / event store  
- No player-local pedagogy strategies  
- Every new student table → `purge_service._STUDENT_TABLES` same PR  
- Media blob purge must be complete  
- Tests required per EPIC (DoD)  
- Branch: `feat/immersive-learning-*` from main or `v0.1.0-rc2`; never move RC1/RC2 tags  

---

## 1. Recommended order

```
P0 ADRs
→ EPIC-ML-01 Domain Model
→ EPIC-ML-05 LearningEvent taxonomy + contract tests
→ EPIC-ML-02 Media Storage
→ EPIC-ML-03 Transcript
→ EPIC-ML-06 Evidence mapping + Memory Router skeleton
→ EPIC-ML-07 Cognitive Projection
→ EPIC-ML-08 Policy scaffold
→ EPIC-ML-09 FSRS eligibility wiring
→ EPIC-ML-04 Player (can parallel after 01–03)
→ EPIC-ML-10 Practice
→ EPIC-ML-15 UX polish
→ EPIC-ML-11 Transfer
→ EPIC-ML-12 Privacy (continuous; gate before beta)
→ EPIC-ML-14 Observability
→ EPIC-ML-13 Evaluation
```

Parallelism: 04 Player frontend // 05–09 backend after schema; 10 depends on 04+08; 11 after 10.

---

## EPIC-ML-01 Domain Model

| Field | Content |
|-------|---------|
| Goal | Introduce MediaAsset, Transcript, TranscriptSegment, LearningUnit, occurrence edges, MediaSession contracts |
| Files/modules | `services/models.py`, new `services/immersive/` or `omodul` stubs, Master ADR refs, `event_schema` docs |
| Models | MediaAsset, Transcript, TranscriptSegment, LearningUnit, LearningUnitOccurrence, MediaSession |
| APIs | CRUD read models (feature-flagged); no player yet |
| Events | none required |
| Tests | schema constraints; LearningUnit ≠ segment_id identity test |
| Migration | yes (additive) |
| Acceptance | tables exist; purge list updated; no RC2 breakage |
| Dependencies | ADRs approved |
| Risk | over-binding subtitle as LU |

---

## EPIC-ML-02 Media Storage

| Field | Content |
|-------|---------|
| Goal | Upload → object storage → signed playback URL; provenance |
| Files | `services/storage.py`, `vendor/obase/oss.py`, upload router, media bucket config |
| Models | MediaAsset.storage_ref, content_provenance |
| APIs | `POST /media`, `GET /media/{id}`, signed URL |
| Events | optional media_registered (not LearningEvent) |
| Tests | upload auth; cross-user deny; blob path isolation |
| Migration | maybe columns only |
| Acceptance | V1 LOCAL_UPLOAD + OBJECT_STORAGE work; no DRM bypass APIs |
| Dependencies | ML-01 |
| Risk | orphan blobs; oversized uploads |

---

## EPIC-ML-03 Transcript

| Field | Content |
|-------|---------|
| Goal | SRT/VTT upload + normalize + segment rows + optional translation field |
| Files | transcript parser (clean-room), services, workers stub |
| Models | Transcript, TranscriptSegment |
| APIs | attach transcript; list segments windowed |
| Events | provenance on generated fields |
| Tests | SRT/VTT fixtures; 10k segment pagination; idempotent re-upload |
| Migration | yes if not in 01 |
| Acceptance | player can fetch cues by media_id |
| Dependencies | ML-01/02 |
| Risk | AGPL parser copy; encoding issues |

---

## EPIC-ML-04 Player

| Field | Content |
|-------|---------|
| Goal | mneme-web Immersive workspace: video, transcript, controls, keyboard-first |
| Files | mneme-web routes/components (separate repo) |
| Models | consumes MediaSession |
| APIs | session create/resume; event ingest batch |
| Events | emits taxonomy via client → API |
| Tests | frontend unit + E2E happy path |
| Migration | no |
| Acceptance | prev/next/repeat/loop/speed/subtitle/translation/lookup/bookmark/practice entry |
| Dependencies | ML-02/03/05 |
| Risk | telemetry as LearningEvent |

---

## EPIC-ML-05 LearningEvent

| Field | Content |
|-------|---------|
| Goal | Formal video taxonomy + ADR + contract tests; Telemetry vs LearningEvent boundary |
| Files | `packages/event-schema`, `outputs/VIDEO-LEARNING-EVENT-TAXONOMY.md` → code constants/tests, ingest guards |
| Models | no table change required |
| APIs | existing append + product ingest; media batch endpoint |
| Events | full V1 taxonomy subset |
| Tests | idempotency; taxonomy allowlist for media source; no p_mastery in payload |
| Migration | no |
| Acceptance | contract tests green; duplicate event no double write |
| Dependencies | ADR Telemetry vs LearningEvent |
| Risk | open vocabulary sprawl |

---

## EPIC-ML-06 Evidence

| Field | Content |
|-------|---------|
| Goal | Map video LearningEvents → Evidence with strength classes |
| Files | `services/evidence_graph.py`, media evidence mapper, Memory Router skeleton |
| Models | evidence_type extensions; optional derived aggregate table |
| APIs | internal |
| Events | RESULT events → MemoryEvidence |
| Tests | replay≠misunderstanding; lookup≠strong; listening miss=performance |
| Migration | maybe |
| Acceptance | evidence levels respected; claims require refs |
| Dependencies | ML-05 |
| Risk | over-claiming from behavior |

---

## EPIC-ML-07 Cognitive Projection

| Field | Content |
|-------|---------|
| Goal | Project language LUs through CognitiveStateV2 without second state |
| Files | `services/cognitive_state_v2.py`, claim builders, knowledge_ref namespaces |
| Models | LU namespaces `vocab-`/`phrase-`/`grammar-`/`listening-`/`listening_feature-` |
| APIs | explain endpoints include media evidence refs |
| Events | read-only projection |
| Tests | null dims stay null; replay checksum stable |
| Migration | no state table |
| Acceptance | same evidence → same projection |
| Dependencies | ML-06 |
| Risk | stuffing priors as evidence |

---

## EPIC-ML-08 Policy

| Field | Content |
|-------|---------|
| Goal | Scaffold L0–L5 + media practice candidates in Policy Engine |
| Files | `mneme_core/policy_engine.py`, `policy_trace.py`, `product_closure.build_learn_now` |
| Models | PolicyDecision reason_codes for scaffold |
| APIs | Learn Now returns VIDEO_* / DICTATION_* candidates |
| Events | SCAFFOLD_LEVEL_CHANGED with decision_id |
| Tests | player has no pedagogy ifs (AST/lint); override not mastery; uncertainty diagnostic |
| Migration | no |
| Acceptance | policy owns pause/reveal/review/transfer recommendations |
| Dependencies | ML-07 |
| Risk | frontend re-implements policy |

---

## EPIC-ML-09 FSRS

| Field | Content |
|-------|---------|
| Goal | Memory Router eligibility → single FSRS authority |
| Files | new `services/memory_router.py` (name TBD), vocab_service alignment, cognitive write path |
| Models | link LU → kc_mastery KP |
| APIs | internal |
| Events | only eligible RESULT/review advance schedule |
| Tests | lookup no item; massed replay no spaced advance; duplicate no double update |
| Migration | maybe mapping table |
| Acceptance | no second scheduler; deterministic FSRS on eligible evidence |
| Dependencies | ML-06/07 |
| Risk | practice spam pushing intervals |

---

## EPIC-ML-10 Practice

| Field | Content |
|-------|---------|
| Goal | Listening comprehension + dictation + fill-blank on current segment |
| Files | practice omodul/oskill, routers, frontend practice sheet |
| Models | task definitions versioned |
| APIs | start/submit practice |
| Events | *_ATTEMPT / *_RESULT |
| Tests | deterministic scoring; scaffold level recorded |
| Migration | maybe |
| Acceptance | results become performance Evidence |
| Dependencies | ML-04/08/09 |
| Risk | LLM grading without verifier |

---

## EPIC-ML-11 Transfer

| Field | Content |
|-------|---------|
| Goal | Cross-context review of same LearningUnit |
| Files | transfer item generator, `transfer_probe_service` extension, evaluation_phase wiring |
| Models | source/target context metadata |
| APIs | transfer task fetch/submit |
| Events | TRANSFER_* |
| Tests | near vs far tagging; independent_no_ai flags |
| Migration | maybe |
| Acceptance | Video A pattern tested via Video B / generated example |
| Dependencies | ML-09/10 |
| Risk | paraphrases too close → memorization |

---

## EPIC-ML-12 Privacy

| Field | Content |
|-------|---------|
| Goal | Classification, export redaction, purge completeness including object storage |
| Files | `purge_service.py`, export adapters, retention docs |
| Models | privacy_class on media rows |
| APIs | delete/export include media |
| Events | — |
| Tests | purge residual=0 for DB+blobs; cross-user isolation |
| Migration | as needed |
| Acceptance | FC-2 style: new tables in purge list; storage_cleanup_pending empty on success |
| Dependencies | ML-01/02 continuous |
| Risk | orphan media; voice P3 mishandling |

---

## EPIC-ML-13 Evaluation

| Field | Content |
|-------|---------|
| Goal | Cohort metrics for immersive: retention, transfer, scaffold dependency |
| Files | `evaluation_os.py`, pilot protocol endpoints |
| Models | ledger projections |
| APIs | insights |
| Events | evaluation_phase tagged |
| Tests | contamination filters |
| Migration | no |
| Acceptance | dashboards distinguish observational vs randomized |
| Dependencies | ML-10/11 |
| Risk | causal overclaim |

---

## EPIC-ML-14 Observability

| Field | Content |
|-------|---------|
| Goal | End-to-end trace MediaSession→…→FSRS answerability |
| Files | observability hooks, why-this explainers |
| Models | trace_id propagation |
| APIs | debug/explain (authz) |
| Events | — |
| Tests | golden traces |
| Migration | no |
| Acceptance | three “why” questions answerable from stored traces |
| Dependencies | ML-05–09 |
| Risk | PII in traces |

---

## EPIC-ML-15 UX

| Field | Content |
|-------|---------|
| Goal | Transcript virtualization, status chips, keyboard map, resume UX polish |
| Files | mneme-web |
| Models | — |
| APIs | search segments |
| Events | telemetry only for chrome |
| Tests | a11y + mobile viewport; E2E keyboard |
| Migration | no |
| Acceptance | 10k segments usable; not a cluttered dashboard |
| Dependencies | ML-04 |
| Risk | over-UI |

---

## 2. Test strategy (cross-cutting)

| Layer | Focus |
|-------|-------|
| Unit | parsers, eligibility, scoring, policy scoring |
| Integration | upload→transcript→session→event→evidence |
| Projection | CognitiveState rebuild checksum |
| Replay | identical evidence → identical state & FSRS |
| Idempotency | duplicate event_id |
| Policy | scaffold decisions + override behavior |
| FSRS | eligibility matrix |
| Privacy/purge | residual 0 |
| Cross-user | IDOR on media |
| Frontend / E2E | player flows |
| Performance | 10k segments, seek, ingest flood |

**Invariants**

1. Same evidence replay → same cognitive state  
2. Same eligible memory evidence → deterministic FSRS state  
3. Duplicate event → no double update  
4. Purge → media/student residual = 0  

---

## 3. P0 architecture decisions (must land first)

1. Media Learning Engine boundary  
2. Telemetry vs LearningEvent vs Evidence  
3. Transcript ≠ LearningUnit identity  
4. Scaffold Policy ownership  
5. Media Evidence strength  
6. FSRS single authority + Memory Router  
7. Content provenance + external provider non-bypass  
8. Clean-room / AGPL non-copy  

---

## 4. MVP scope freeze

In: upload video, SRT/VTT, player, sentence nav/repeat/loop, bilingual toggles, lookup, comprehension, dictation, events, evidence, CognitiveState, policy scaffold, FSRS eligibility, resume.  

Out: YouTube downloader, full pronunciation scoring, social, marketplace, complex CDN, auto LU extraction.

---

## 5. EPIC count

**15 EPICs** (ML-01 … ML-15) as specified.
