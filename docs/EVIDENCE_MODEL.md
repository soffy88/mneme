# Evidence model

Mneme uses an evidence chain rather than free-form explanations:

```text
LearningEvent (fact) → EvidenceRef → EvidenceClaim → CognitiveState
```

`EvidenceRef` contains `event_id`, `knowledge_ref`, `evidence_type`,
`occurred_at`, `source`, optional weight/confidence, model and verifier
versions, and an evidence level. `EvidenceClaim` contains the claim type/value,
knowledge reference, evidence refs, model version, computation time,
uncertainty, and evidence level.

The only accepted evidence levels are:

| Level | Meaning | Learning-effect claim |
|---|---|---|
| `contract` | deterministic schema/kernel/guard behavior | never |
| `offline` | replay or public/offline evaluation | never |
| `observational` | real product events without random assignment | no causal claim |
| `randomized` | a registered randomized protocol with eligible endpoints | protocol-scoped only |
| `commercial` | real funnel, retention, pricing, or payment data | measured cohort/window only |

Claims with a value require at least one same-student evidence reference.
Unknown values may have no refs and remain explicitly unknown. LLMs may explain
claims returned by `explain_cognitive_state`; they cannot create claims or
evidence refs.

`P2`/`P3` event payloads are redacted by default in xAPI, Caliper, CASE, and
parent/process exports. Hard delete includes evidence and policy traces.
