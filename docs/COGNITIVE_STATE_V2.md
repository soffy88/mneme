# Cognitive State v2

`CognitiveStateV2` is a read-only projection. `LearningEvent` remains the fact
source and `SubmitAnswer` → `omodul.cognitive` remains the only mastery write
path. The projection does not write `kc_mastery` and does not replace BKT or
FSRS.

## Contract

The projection contains identity, BKT mastery probability/confidence/evidence
count, FSRS memory fields, recognition, explicit transfer, evidence-backed
misconceptions, explicit metacognition, uncertainty, and provenance. Unsupported
dimensions are `null`/unknown; no prior is presented as observed evidence.

The uncertainty contract is centralized in
`services.cognitive_state_v2.UNCERTAINTY_RULES` and is versioned. It is a
conservative evidence sufficiency heuristic, not a new Bayesian learner model.

## Replay and comparison

`CognitiveStateV2.rebuild(db, student_id, knowledge_ref, as_of)` loads v2 facts,
falls back to the legacy adapter during the dual-write window, and reuses the
existing BKT/FSRS replay runner. `from_observations` is the deterministic pure
projection used by contract tests. `compare()` reports changed dimensions and
version/checksum identity without treating a projection as fact.

No event or event payload can contain `p_mastery`; a missing observation is not
converted into a prior-looking learner number.
